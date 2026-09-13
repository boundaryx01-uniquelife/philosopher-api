import os
import json
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Dict, Optional
import google.generativeai as genai

import config
from prompt_templates import get_system_prompt
from RAG.parser import load_and_parse_file
from RAG.vector_store import add_philosopher_texts, query_philosopher_context
from database import get_db_connection

app = FastAPI(
    title="철학자와의 대화 API 서버",
    description="대규모 고전 원문 RAG(검색 증강 생성) 및 실시간 스트리밍을 활용하여 깊이 있는 사색과 위로를 전하는 API 서버입니다.",
    version="2.0.0"
)

# CORS 설정 (모든 도메인 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic 모델 정의
class ChatMessage(BaseModel):
    role: str = Field(..., description="메시지 전송자 ('user' 또는 'model' / 'assistant')")
    content: str = Field(..., description="메시지 내용")

class ChatRequest(BaseModel):
    philosopher_id: str = Field(..., description="상담할 철학자 ID (예: nietzsche, schopenhauer)")
    message: str = Field(..., description="사용자의 현재 고민/질문 내용")
    chat_history: Optional[List[ChatMessage]] = Field(default=[], description="이전 대화 기록 (맥락 보존용)")

class ChatResponse(BaseModel):
    philosopher_id: str
    reply: str
    retrieved_context: List[str]

# 대규모 원문 데이터베이스 자동 갱신 및 인덱싱 작업
def index_philosopher_texts(force_reload: bool = False):
    """data/original_texts 안의 대규모 텍스트 파일들을 읽어 SQLite DB에 적재합니다."""
    print("[RAG] Initializing comprehensive classical vector database indexing...")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    texts_dir = os.path.join(base_dir, "data", "original_texts")
    
    if not os.path.exists(texts_dir):
        print(f"[RAG] Warning: Text directory not found at {texts_dir}")
        return
        
    for phil_id in config.PHILOSOPHERS.keys():
        file_path = os.path.join(texts_dir, f"{phil_id}.txt")
        if os.path.exists(file_path):
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM vector_store WHERE philosopher_id = ?", (phil_id,))
                count = cursor.fetchone()[0]
                
                # 데이터가 10개 미만이거나 force_reload인 경우 대규모 데이터로 재인덱싱
                if count < 8 or force_reload:
                    cursor.execute("DELETE FROM vector_store WHERE philosopher_id = ?", (phil_id,))
                    conn.commit()
                    conn.close()
                    print(f"[RAG] Re-indexing expanded corpus for {phil_id}...")
                    chunks = load_and_parse_file(file_path, chunk_size=350, chunk_overlap=60)
                    add_philosopher_texts(phil_id, chunks)
                else:
                    conn.close()
                    print(f"[RAG] Philosopher {phil_id} already has {count} comprehensive items. Skipping indexing.")
            except Exception as e:
                print(f"[RAG] Error processing {phil_id}: {e}")
        else:
            print(f"[RAG] Warning: Text file for {phil_id} not found at {file_path}")

@app.on_event("startup")
def startup_event():
    if config.GEMINI_API_KEY:
        index_philosopher_texts()
    else:
        print("[WARNING] Startup: Gemini API Key is missing. Skipping auto-indexing.")

# API 엔드포인트
@app.get("/api/philosophers", summary="사용 가능한 철학자 목록 조회")
def get_philosophers():
    return list(config.PHILOSOPHERS.values())

def get_best_model_name():
    """Gemini API 키 권한별 지원 모델을 자동 탐색합니다."""
    try:
        supported_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                supported_models.append(m.name)
        
        for m_name in supported_models:
            if "flash" in m_name:
                return m_name
        if supported_models:
            return supported_models[0]
    except Exception as list_err:
        print(f"[ModelListError] {list_err}")
    return "models/gemini-1.5-flash"

@app.post("/api/chat", response_model=ChatResponse, summary="철학자와의 대화 (동기 방식)")
def chat_with_philosopher(request: ChatRequest):
    phil_id = request.philosopher_id.lower()
    if phil_id not in config.PHILOSOPHERS:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 철학자 ID입니다. 지원 목록: {list(config.PHILOSOPHERS.keys())}")
        
    retrieved_context = query_philosopher_context(phil_id, request.message, n_results=3)
    context_str = "\n\n".join(retrieved_context) if retrieved_context else ""
    system_prompt = get_system_prompt(phil_id, context_str, request.message)
    
    try:
        formatted_history = []
        for msg in request.chat_history:
            role = "user" if msg.role.lower() == "user" else "model"
            formatted_history.append({"role": role, "parts": [msg.content]})
            
        selected_model_name = get_best_model_name()
        model = genai.GenerativeModel(model_name=selected_model_name, system_instruction=system_prompt)
        chat = model.start_chat(history=formatted_history)
        response = chat.send_message(request.message)
        
        return ChatResponse(
            philosopher_id=phil_id,
            reply=response.text,
            retrieved_context=retrieved_context
        )
    except Exception as e:
        print(f"[ChatError] {e}")
        raise HTTPException(status_code=500, detail=f"AI 서버 통신 중 오류가 발생했습니다: {str(e)}")

@app.post("/api/chat/stream", summary="철학자와의 대화 (초고속 실시간 타자 스트리밍 방식)")
def chat_with_philosopher_stream(request: ChatRequest):
    """
    0.5초 만에 답변 생성이 시작되는 실시간 타자기(Streaming) API입니다.
    """
    phil_id = request.philosopher_id.lower()
    if phil_id not in config.PHILOSOPHERS:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 철학자 ID입니다.")
        
    retrieved_context = query_philosopher_context(phil_id, request.message, n_results=3)
    context_str = "\n\n".join(retrieved_context) if retrieved_context else ""
    system_prompt = get_system_prompt(phil_id, context_str, request.message)
    
    formatted_history = []
    for msg in request.chat_history:
        role = "user" if msg.role.lower() == "user" else "model"
        formatted_history.append({"role": role, "parts": [msg.content]})
        
    selected_model_name = get_best_model_name()

    def generate_stream():
        yield json.dumps({"type": "metadata", "retrieved_context": retrieved_context}, ensure_ascii=False) + "\n"
        
        try:
            model = genai.GenerativeModel(model_name=selected_model_name, system_instruction=system_prompt)
            chat = model.start_chat(history=formatted_history)
            response = chat.send_message(request.message, stream=True)
            
            for chunk in response:
                if chunk.text:
                    yield json.dumps({"type": "chunk", "text": chunk.text}, ensure_ascii=False) + "\n"
        except Exception as e:
            print(f"[StreamError] {e}")
            yield json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False) + "\n"

    return StreamingResponse(generate_stream(), media_type="application/x-ndjson")

@app.post("/api/admin/initialize-rag", summary="RAG 데이터 수동 초기화 및 강제 재색인")
def force_reindex(background_tasks: BackgroundTasks):
    background_tasks.add_task(index_philosopher_texts, force_reload=True)
    return {"message": "대규모 RAG 데이터베이스 강제 재색인 작업이 백그라운드에서 시작되었습니다."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
