# Noelle_Bot/ai_services/deep_search_service.py

import os
import google.genai as genai
from google.genai import types as genai_types
from google.api_core import exceptions as google_exceptions
import logging
import asyncio
import discord
from typing import List, Optional, Tuple

# --- Konfigurasi (tetap sama) ---
_logger = logging.getLogger("noelle_bot.ai.deep_search")
DEEP_RESEARCH_API_KEY = os.getenv('DEEP_RESEARCH_API_KEY')
PLANNER_REPORTER_MODEL = "models/gemini-2.5-flash-preview-05-20"
SEARCHER_MODEL = "models/gemini-2.0-flash"
RATE_LIMIT_DELAY_SECONDS = 4.1

# --- PERBAIKAN: Prompt Template yang Ditingkatkan ---

PLANNER_CLARIFICATION_PROMPT_TEMPLATE = """
Anda adalah seorang Analis Riset Senior yang sangat berpengalaman.
Tujuan utama Anda adalah untuk memahami secara mendalam maksud pengguna sebelum memulai riset agar hasilnya sangat relevan.
Seorang pengguna memberikan topik awal: "{topic}"

Tugas Anda: Buat 2-4 pertanyaan klarifikasi yang cerdas dan terbuka untuk menggali lebih dalam. Fokus pada:
- **Angle & Perspektif:** Apa sudut pandang yang paling diminati? (misalnya: teknis, finansial, sosial, sejarah)
- **Skop & Batasan:** Apakah ada batasan spesifik? (misalnya: periode waktu, wilayah geografis, untuk pemula, untuk ahli)
- **Tujuan Akhir:** Untuk apa laporan ini akan digunakan? (misalnya: presentasi bisnis, tugas sekolah, rasa ingin tahu pribadi)

Contoh pertanyaan yang baik:
- "Dari sudut pandang apa Anda paling tertarik membahas topik ini? Apakah dari sisi teknologinya, dampak sosialnya, atau mungkin dari perspektif bisnis?"
- "Apakah ada periode waktu atau wilayah geografis tertentu yang ingin Anda fokuskan dalam riset ini?"
- "Untuk siapa laporan ini ditujukan? Ini akan membantu saya menyesuaikan kedalaman teknisnya."

Hasilkan HANYA daftar pertanyaan bernomor. Jangan tambahkan pembukaan atau penutup apa pun.
"""

# ... sisa template lainnya tetap sama ...
PLANNER_PROMPT_TEMPLATE = """
Anda adalah seorang Asisten Perencana Riset AI yang sangat teliti.
Tugas Anda adalah mengambil sebuah topik utama dan konteks tambahan dari pengguna, lalu memecahnya menjadi {num_queries} sub-topik penelitian yang spesifik.
Pastikan sub-topik tersebut mencerminkan konteks yang diberikan pengguna.
Hasilkan daftar sub-topik dalam format daftar bernomor (1., 2., 3., dst.). Jangan tambahkan teks atau pembukaan lain, hanya daftar bernomor.

Topik Utama: "{topic}"
Konteks Tambahan dari Pengguna: "{user_context}"
"""

SEARCHER_PROMPT_TEMPLATE = """
Anda adalah seorang Asisten Peneliti AI. Fokus Anda adalah mengumpulkan informasi faktual dan data mentah dari internet untuk sub-topik yang diberikan.
Gunakan kemampuan pencarian Anda untuk menemukan informasi paling relevan dan detail.
Sajikan hasilnya sebagai teks informatif yang padat.

Sub-Topik untuk Diteliti: "{sub_topic}"
"""

REPORTER_PROMPT_TEMPLATE = """
Anda adalah seorang Penulis Laporan AI profesional.
Tugas Anda adalah mengambil kumpulan data penelitian mentah dan melakukan DUA hal:
1.  Tulis sebuah Ringkasan Eksekutif yang singkat dan padat (maksimal 2-3 paragraf) dari temuan utama.
2.  Tulis sebuah Laporan Mendalam yang komprehensif, terstruktur dengan baik, dan mudah dibaca, berdasarkan semua data yang diberikan. Gunakan format Markdown untuk heading, sub-heading, dan list.

PENTING: Struktur output Anda HARUS mengikuti format ini dengan tepat, termasuk penanda [SUMMARY_START], [SUMMARY_END], dan [REPORT_START]:

[SUMMARY_START]
(Tulis ringkasan eksekutif Anda di sini.)
[SUMMARY_END]

[REPORT_START]
(Tulis laporan mendalam lengkap Anda di sini, gunakan Markdown.)

{follow_up_instructions}

Data Penelitian Mentah:
---
{research_data}
---
"""
# --- Inisialisasi Klien (tetap sama) ---
_deep_search_client: Optional[genai.Client] = None

def initialize_deep_search_client():
    global _deep_search_client
    if not DEEP_RESEARCH_API_KEY:
        _logger.error("DEEP_RESEARCH_API_KEY tidak diatur. Fitur Deep Search dinonaktifkan.")
        _deep_search_client = None
        return
    if _deep_search_client:
        return
    try:
        _logger.info("Menginisialisasi klien Gemini khusus untuk Deep Search...")
        _deep_search_client = genai.Client(api_key=DEEP_RESEARCH_API_KEY)
        _logger.info("Klien Deep Search berhasil diinisialisasi.")
    except Exception as e:
        _logger.critical(f"Gagal inisialisasi klien Deep Search: {e}", exc_info=True)
        _deep_search_client = None
initialize_deep_search_client()

# --- Fungsi-fungsi Agen (dengan perbaikan besar) ---

async def generate_questions(topic: str) -> Optional[str]:
    # ... fungsi ini tetap sama, tetapi sekarang menggunakan template yang lebih baik ...
    if not _deep_search_client: return None
    prompt = PLANNER_CLARIFICATION_PROMPT_TEMPLATE.format(topic=topic)
    try:
        response = await asyncio.to_thread(
            _deep_search_client.models.generate_content, model=PLANNER_REPORTER_MODEL, contents=prompt
        )
        return response.text
    except Exception as e:
        _logger.error(f"Gagal generate pertanyaan klarifikasi: {e}")
        return None

async def _run_planner(topic: str, mode: str, user_context: str) -> List[str]:
    # ... fungsi ini tetap sama ...
    num_queries = 4 if mode == "fast" else 6
    prompt = PLANNER_PROMPT_TEMPLATE.format(topic=topic, num_queries=num_queries, user_context=user_context)
    response = await asyncio.to_thread(
        _deep_search_client.models.generate_content, model=PLANNER_REPORTER_MODEL, contents=prompt
    )
    sub_topics = [line.strip() for line in response.text.split('\n') if line.strip() and line.startswith(tuple(f"{i}." for i in range(10)))]
    _logger.info(f"Planner menghasilkan {len(sub_topics)} sub-topik untuk '{topic}' dengan konteks.")
    return sub_topics

async def _run_searcher_for_sub_topic(sub_topic: str) -> Tuple[str, List[str]]:
    """
    --- FUNGSI YANG DIPERBAIKI SECARA TOTAL ---
    Menjalankan agen Peneliti dan mengembalikan teks beserta sumber dari grounding_metadata.
    """
    prompt = SEARCHER_PROMPT_TEMPLATE.format(sub_topic=sub_topic)
    config = genai_types.GenerateContentConfig(
        tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())]
    )
    
    response = await asyncio.to_thread(
        _deep_search_client.models.generate_content, model=SEARCHER_MODEL, contents=prompt, config=config
    )
    
    result_text = ""
    sources = []
    
    if response.candidates:
        candidate = response.candidates[0]
        # Ekstrak teks utama
        if hasattr(candidate.content, 'parts') and candidate.content.parts:
            result_text = "".join([p.text for p in candidate.content.parts if hasattr(p, 'text')])
        
        # --- PERBAIKAN LOGIKA EKSTRAKSI SUMBER ---
        # Gunakan grounding_metadata, bukan citation_metadata
        if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata and hasattr(candidate.grounding_metadata, 'grounding_chunks'):
            for chunk in candidate.grounding_metadata.grounding_chunks:
                if chunk.web and chunk.web.uri:
                    if chunk.web.uri not in sources:
                        sources.append(chunk.web.uri)
    
    # Fallback jika tidak ada teks di 'parts'
    if not result_text and hasattr(response, 'text'):
        result_text = response.text

    return f"### Riset untuk: {sub_topic}\n\n{result_text}\n\n---\n\n", sources


async def _run_reporter(original_topic: str, research_data: str, follow_up: Optional[str]) -> str:
    # ... fungsi ini tetap sama ...
    follow_up_instructions = ""
    if follow_up:
        follow_up_instructions = f"PENTING: Setelah menyusun laporan utama, jawab juga pertanyaan spesifik berikut di bagian akhir:\n- {follow_up}"
    prompt = REPORTER_PROMPT_TEMPLATE.format(research_data=research_data, follow_up_instructions=follow_up_instructions)
    response = await asyncio.to_thread(
        _deep_search_client.models.generate_content, model=PLANNER_REPORTER_MODEL, contents=prompt
    )
    return f"## Laporan Riset Mendalam: {original_topic}\n\n{response.text}"


# --- Fungsi Orkestrasi Utama (sedikit modifikasi untuk menangani output baru) ---
async def run_deep_search(interaction: discord.Interaction, topic: str, mode: str, user_context: str, follow_up: Optional[str]) -> Tuple[str, List[str]]:
    # ... (logika utama tetap sama, perhatikan penanganan tuple `result_text, sources`) ...
    if not _deep_search_client:
        return "Maaf, fitur Deep Search sedang tidak tersedia karena masalah konfigurasi API Key.", []

    try:
        await interaction.edit_original_response(content="`Tahap 1/3` 🧠 **Merencanakan riset berdasarkan jawaban Anda...**", view=None)
        sub_topics = await _run_planner(topic, mode, user_context)
        if not sub_topics: return "Maaf, saya gagal merencanakan riset untuk topik ini.", []

        research_results = []
        all_sources = set() # Gunakan set untuk menghindari duplikasi sumber
        total_sub_topics = len(sub_topics)
        for i, sub_topic in enumerate(sub_topics):
            status_msg = f"`Tahap 2/3` ⏳ **Meneliti sub-topik ({i+1}/{total_sub_topics}):**\n> {sub_topic[:100]}"
            await interaction.edit_original_response(content=status_msg, view=None)
            
            try:
                result_text, sources = await _run_searcher_for_sub_topic(sub_topic)
                research_results.append(result_text)
                for src in sources: all_sources.add(src)
                _logger.info(f"Penelitian untuk '{sub_topic}' selesai, {len(sources)} sumber unik ditemukan.")
            except Exception as search_err:
                _logger.error(f"Gagal meneliti sub-topik '{sub_topic}': {search_err}", exc_info=True)
                research_results.append(f"### Riset untuk: {sub_topic}\n\n**[GAGAL]** Terjadi kesalahan saat meneliti sub-topik ini.\n\n---\n\n")

            if i < total_sub_topics - 1: await asyncio.sleep(RATE_LIMIT_DELAY_SECONDS)

        await interaction.edit_original_response(content="`Tahap 3/3` ✍️ **Menyusun laporan akhir...**", view=None)
        combined_research = "".join(research_results)
        
        final_report = await _run_reporter(topic, combined_research, follow_up)
        
        _logger.info(f"Deep Search untuk topik '{topic}' selesai.")
        return final_report, sorted(list(all_sources)) # Kembalikan sebagai list yang terurut

    except google_exceptions.GoogleAPIError as e:
        return f"Terjadi kesalahan pada API Google: {e.message}", []
    except Exception as e:
        return f"Terjadi kesalahan tak terduga: `{type(e).__name__}`.", []