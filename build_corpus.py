"""
==========================================================================
5대 철학자 고전 전집 자동 수집 및 RAG 코퍼스 빌더 (Full-Text Corpus Builder)
==========================================================================
프로젝트 구텐베르크(Project Gutenberg)의 저작권 만료 전자책에서
5대 철학자의 대표 저작 전문(Full Text)을 자동 다운로드하여
data/original_texts/ 폴더에 초거대 코퍼스로 적재합니다.
==========================================================================
"""

import urllib.request
import os
import re
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "original_texts")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# =========================================================================
# 프로젝트 구텐베르크 도서 ID 매핑
# =========================================================================
GUTENBERG_BOOKS = {
    "nietzsche": [
        {"id": 1998,  "title": "Thus Spake Zarathustra (짜라투스트라는 이렇게 말했다)"},
        {"id": 4363,  "title": "Beyond Good and Evil (선악의 저편)"},
        {"id": 52263, "title": "The Twilight of the Idols (우상의 황혼)"},
        {"id": 19322, "title": "The Antichrist (적그리스도)"},
        {"id": 38145, "title": "Human, All Too Human (인간적인 너무나 인간적인)"},
        {"id": 7202,  "title": "Ecce Homo (이 사람을 보라)"},
        {"id": 7205,  "title": "The Case of Wagner (바그너의 경우)"},
        {"id": 7200,  "title": "The Birth of Tragedy (비극의 탄생)"},
        {"id": 37841, "title": "On the Genealogy of Morals (도덕의 계보)"},
    ],
    "schopenhauer": [
        {"id": 10741, "title": "The Art of Controversy (논쟁의 기술)"},
        {"id": 10732, "title": "The Wisdom of Life (인생의 지혜)"},
        {"id": 10714, "title": "Counsels and Maxims (교훈과 격률)"},
        {"id": 10715, "title": "Religion, A Dialogue (종교 대화)"},
        {"id": 10716, "title": "Studies in Pessimism (비관주의 연구)"},
        {"id": 10717, "title": "On Human Nature (인간의 본성에 관하여)"},
        {"id": 11945, "title": "The World as Will and Idea Vol.1 (의지와 표상으로서의 세계 1)"},
        {"id": 38427, "title": "The World as Will and Idea Vol.2 (의지와 표상으로서의 세계 2)"},
        {"id": 40868, "title": "The World as Will and Idea Vol.3 (의지와 표상으로서의 세계 3)"},
    ],
    "epictetus": [
        {"id": 45109, "title": "The Enchiridion (엥케이리디온/편람)"},
        {"id": 10661, "title": "The Discourses of Epictetus (담론록)"},
        {"id": 57166, "title": "The Golden Sayings of Epictetus (에픽테토스의 금언집)"},
    ],
    "socrates": [
        {"id": 1656,  "title": "Apology (소크라테스의 변론)"},
        {"id": 1657,  "title": "Crito (크리톤)"},
        {"id": 1658,  "title": "Phaedo (파이돈)"},
        {"id": 1600,  "title": "Symposium (향연)"},
        {"id": 1497,  "title": "The Republic (국가)"},
        {"id": 1636,  "title": "Meno (메논)"},
        {"id": 1726,  "title": "Euthyphro (에우튀프론)"},
        {"id": 1580,  "title": "Protagoras (프로타고라스)"},
        {"id": 1598,  "title": "Gorgias (고르기아스)"},
        {"id": 1616,  "title": "Allegory of the Cave / Republic VII (동굴의 비유)"},
    ],
    "confucius": [
        {"id": 3330,  "title": "The Analects (논어)"},
        {"id": 4094,  "title": "The Sayings of Confucius (공자의 말씀)"},
        {"id": 3100,  "title": "The Great Learning (대학)"},
        {"id": 3176,  "title": "The Doctrine of the Mean (중용)"},
        {"id": 4093,  "title": "Mencius (맹자)"},
    ],
}

def fetch_gutenberg_text(book_id: int) -> str:
    """프로젝트 구텐베르크에서 전자책 전문(Full Text)을 다운로드합니다."""
    # 다양한 미러 URL 시도
    urls = [
        f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt",
        f"https://www.gutenberg.org/files/{book_id}/{book_id}-0.txt",
        f"https://www.gutenberg.org/files/{book_id}/{book_id}.txt",
    ]
    
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'PhilosopherRAG/1.0 (Educational Research Project)'
            })
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read()
                # UTF-8 시도 후 Latin-1 폴백
                try:
                    text = raw.decode('utf-8')
                except UnicodeDecodeError:
                    text = raw.decode('latin-1')
                
                if len(text) > 500:
                    return text
        except Exception as e:
            continue
    
    return ""


def clean_gutenberg_text(raw_text: str) -> str:
    """구텐베르크 전자책의 머리말/꼬리말/라이선스 부분을 제거하고 본문만 추출합니다."""
    if not raw_text:
        return ""
    
    # 구텐베르크 헤더/푸터 제거
    start_markers = [
        "*** START OF THIS PROJECT GUTENBERG",
        "*** START OF THE PROJECT GUTENBERG",
        "***START OF THIS PROJECT GUTENBERG",
        "***START OF THE PROJECT GUTENBERG",
        "*END*THE SMALL PRINT",
    ]
    end_markers = [
        "*** END OF THIS PROJECT GUTENBERG",
        "*** END OF THE PROJECT GUTENBERG",
        "***END OF THIS PROJECT GUTENBERG",
        "***END OF THE PROJECT GUTENBERG",
        "End of the Project Gutenberg",
        "End of Project Gutenberg",
    ]
    
    text = raw_text
    
    for marker in start_markers:
        idx = text.find(marker)
        if idx != -1:
            # 마커 이후의 첫 빈 줄 다음부터 시작
            newline_idx = text.find('\n\n', idx)
            if newline_idx != -1:
                text = text[newline_idx + 2:]
            break
    
    for marker in end_markers:
        idx = text.find(marker)
        if idx != -1:
            text = text[:idx]
            break
    
    # 여러 줄 빈 줄을 2줄로 통일
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    
    return text.strip()


def build_philosopher_corpus(philosopher_id: str, books: list) -> str:
    """한 철학자의 모든 저작을 다운로드하여 하나의 대형 코퍼스로 결합합니다."""
    corpus_parts = []
    
    for book in books:
        book_id = book["id"]
        title = book["title"]
        
        print(f"  📥 Downloading: {title} (Gutenberg #{book_id})...", end=" ", flush=True)
        
        raw_text = fetch_gutenberg_text(book_id)
        
        if raw_text:
            cleaned = clean_gutenberg_text(raw_text)
            if len(cleaned) > 200:
                # 챕터 헤더 추가
                header = f"\n{'='*80}\n[{title}]\n{'='*80}\n"
                corpus_parts.append(header + cleaned)
                char_count = len(cleaned)
                print(f"✅ {char_count:,} characters downloaded.")
            else:
                print(f"⚠️ Text too short after cleaning ({len(cleaned)} chars), skipping.")
        else:
            print(f"❌ Failed to download.")
        
        # 구텐베르크 서버 부하 방지 (1초 대기)
        time.sleep(1.5)
    
    return "\n\n".join(corpus_parts)


def main():
    print("=" * 80)
    print("🏛️  5대 철학자 고전 전집 자동 수집기 (Project Gutenberg Full-Text Corpus Builder)")
    print("=" * 80)
    print()
    
    total_chars = 0
    total_books = 0
    
    for philosopher_id, books in GUTENBERG_BOOKS.items():
        print(f"\n📚 [{philosopher_id.upper()}] - {len(books)} books to download:")
        print("-" * 60)
        
        corpus = build_philosopher_corpus(philosopher_id, books)
        
        if corpus:
            output_path = os.path.join(OUTPUT_DIR, f"{philosopher_id}.txt")
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(corpus)
            
            file_size = os.path.getsize(output_path)
            char_count = len(corpus)
            total_chars += char_count
            total_books += len(books)
            
            print(f"  💾 Saved: {output_path}")
            print(f"  📊 File size: {file_size / 1024:.1f} KB ({char_count:,} characters)")
        else:
            print(f"  ⚠️ No texts downloaded for {philosopher_id}")
    
    print("\n" + "=" * 80)
    print(f"🎉 CORPUS BUILD COMPLETE!")
    print(f"   Total characters: {total_chars:,}")
    print(f"   Total size: ~{total_chars / 1024 / 1024:.1f} MB")
    print(f"   Total books processed: {total_books}")
    print(f"   Output directory: {OUTPUT_DIR}")
    print("=" * 80)


if __name__ == "__main__":
    main()
