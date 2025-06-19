# Noelle_Bot/ai_services/deep_search_service.py

import os
import google.genai as genai
from google.genai import types as genai_types
from google.api_core import exceptions as google_exceptions
import logging
import asyncio
import discord
from typing import List, Optional

# --- Konfigurasi Model dan API ---
_logger = logging.getLogger("noelle_bot.ai.deep_search")

DEEP_RESEARCH_API_KEY = os.getenv('DEEP_RESEARCH_API_KEY')
PLANNER_REPORTER_MODEL = "models/gemini-2.5-flash-preview-05-20"
SEARCHER_MODEL = "models/gemini-2.0-flash"
RATE_LIMIT_DELAY_SECONDS = 4.1

# --- Prompt Templates (Tetap Sama) ---
PLANNER_PROMPT_TEMPLATE = """
Anda adalah seorang Asisten Perencana Riset AI yang sangat teliti.
Tugas Anda adalah mengambil sebuah topik utama dan memecahnya menjadi {num_queries} sub-topik penelitian yang spesifik, logis, dan dapat ditindaklanjuti.
Pastikan sub-topik tersebut mencakup berbagai aspek dari topik utama.
Hasilkan daftar sub-topik dalam format daftar bernomor (1., 2., 3., dst.). Jangan tambahkan teks atau pembukaan lain, hanya daftar bernomor.

Topik Utama: "{topic}"
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

# --- Inisialisasi Klien (Tetap Sama) ---
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

# --- Fungsi untuk Setiap Agen ---

async def _run_planner(topic: str, mode: str) -> List[str]:
    """Menjalankan agen Perencana untuk membuat sub-topik."""
    num_queries = 4 if mode == "fast" else 6
    prompt = PLANNER_PROMPT_TEMPLATE.format(topic=topic, num_queries=num_queries)
    
    # --- PERBAIKAN ---
    # Langsung panggil generate_content dari 'models', bukan dari objek 'Model'
    response = await asyncio.to_thread(
        _deep_search_client.models.generate_content,
        model=PLANNER_REPORTER_MODEL,
        contents=prompt
    )
    # -------------------
    
    sub_topics = [line.strip() for line in response.text.split('\n') if line.strip() and line[0].isdigit()]
    _logger.info(f"Planner menghasilkan {len(sub_topics)} sub-topik untuk '{topic}'.")
    return sub_topics

async def _run_searcher_for_sub_topic(sub_topic: str) -> str:
    """Menjalankan agen Peneliti untuk satu sub-topik."""
    prompt = SEARCHER_PROMPT_TEMPLATE.format(sub_topic=sub_topic)
    
    config = genai_types.GenerateContentConfig(
        tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())]
    )
    
    # --- PERBAIKAN ---
    response = await asyncio.to_thread(
        _deep_search_client.models.generate_content,
        model=SEARCHER_MODEL,
        contents=prompt,
        config=config
    )
    # -------------------

    result_text = ""
    if hasattr(response, 'text'):
        result_text = response.text
    elif response.candidates and hasattr(response.candidates[0].content, 'parts'):
        result_text = "".join([p.text for p in response.candidates[0].content.parts if hasattr(p, 'text')])
        
    return f"### Riset untuk: {sub_topic}\n\n{result_text}\n\n---\n\n"

async def _run_reporter(original_topic: str, research_data: str, follow_up: Optional[str]) -> str:
    """Menjalankan agen Pelapor untuk menyusun laporan akhir."""
    follow_up_instructions = ""
    if follow_up:
        follow_up_instructions = f"PENTING: Setelah menyusun laporan utama, jawab juga pertanyaan spesifik berikut di bagian akhir:\n- {follow_up}"

    prompt = REPORTER_PROMPT_TEMPLATE.format(
        research_data=research_data,
        follow_up_instructions=follow_up_instructions
    )
    
    # --- PERBAIKAN ---
    response = await asyncio.to_thread(
        _deep_search_client.models.generate_content,
        model=PLANNER_REPORTER_MODEL,
        contents=prompt
    )
    # -------------------
    
    return f"## Laporan Riset Mendalam: {original_topic}\n\n{response.text}"


# --- Fungsi Orkestrasi Utama (Tetap Sama) ---

async def run_deep_search(interaction: discord.Interaction, topic: str, mode: str, follow_up: Optional[str]) -> str:
    """
    Mengorkestrasi seluruh alur kerja Deep Search, dari perencanaan hingga pelaporan,
    sambil memberikan pembaruan status ke pengguna melalui interaksi Discord.
    """
    if not _deep_search_client:
        _logger.error("run_deep_search dipanggil tetapi klien tidak terinisialisasi.")
        return "Maaf, fitur Deep Search sedang tidak tersedia karena masalah konfigurasi API Key."

    try:
        # Tahap 1: Perencanaan
        await interaction.edit_original_response(content="`Tahap 1/3` 🧠 **Merencanakan riset...**")
        sub_topics = await _run_planner(topic, mode)
        if not sub_topics:
            return "Maaf, saya gagal merencanakan riset untuk topik ini. Coba topik yang lebih spesifik."

        # Tahap 2: Penelitian
        research_results = []
        total_sub_topics = len(sub_topics)
        for i, sub_topic in enumerate(sub_topics):
            status_msg = f"`Tahap 2/3` ⏳ **Meneliti sub-topik ({i+1}/{total_sub_topics}):**\n> {sub_topic[:100]}"
            await interaction.edit_original_response(content=status_msg)
            
            try:
                result = await _run_searcher_for_sub_topic(sub_topic)
                research_results.append(result)
                _logger.info(f"Penelitian untuk '{sub_topic}' selesai.")
            except Exception as search_err:
                _logger.error(f"Gagal meneliti sub-topik '{sub_topic}': {search_err}", exc_info=True)
                research_results.append(f"### Riset untuk: {sub_topic}\n\n**[GAGAL]** Terjadi kesalahan saat meneliti sub-topik ini.\n\n---\n\n")

            # Penerapan Rate Limiting
            if i < total_sub_topics - 1:
                await asyncio.sleep(RATE_LIMIT_DELAY_SECONDS)

        # Tahap 3: Pelaporan
        await interaction.edit_original_response(content="`Tahap 3/3` ✍️ **Menyusun laporan akhir...**")
        combined_research = "".join(research_results)
        
        final_report = await _run_reporter(topic, combined_research, follow_up)
        
        _logger.info(f"Deep Search untuk topik '{topic}' selesai.")
        return final_report

    except google_exceptions.GoogleAPIError as e:
        _logger.error(f"Terjadi Google API Error selama Deep Search: {e}", exc_info=True)
        return f"Terjadi kesalahan pada API Google saat melakukan riset. Coba lagi nanti.\n`Error: {e.message}`"
    except Exception as e:
        _logger.error(f"Terjadi error tak terduga selama Deep Search: {e}", exc_info=True)
        return f"Terjadi kesalahan tak terduga: `{type(e).__name__}`. Proses dihentikan."