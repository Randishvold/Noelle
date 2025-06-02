# Noelle_Bot/utils/ai_utils.py
import discord
import io
import asyncio
import logging
from google.genai import types as genai_types # Untuk type hinting Candidate

_logger = logging.getLogger("noelle_bot.ai_utils")

EMBED_TITLE_LIMIT = 256
EMBED_DESC_LIMIT = 4096
EMBED_FIELD_NAME_LIMIT = 256
EMBED_FIELD_VALUE_LIMIT = 1024
MAX_FIELDS_PER_EMBED = 25
SAFE_CHAR_PER_EMBED = 5800 

async def send_long_text_as_file(target_channel: discord.abc.Messageable, text_content: str, filename: str = "response.txt", initial_message: str = "Respons terlalu panjang, dikirim sebagai file:"):
    try:
        file_data = io.BytesIO(text_content.encode('utf-8'))
        discord_file = discord.File(fp=file_data, filename=filename)
        await target_channel.send(content=initial_message, file=discord_file)
        _logger.info(f"AI_Utils: Mengirim respons panjang sebagai file '{filename}' ke channel {target_channel.id if hasattr(target_channel, 'id') else 'DM'}.")
    except Exception as e:
        _logger.error(f"AI_Utils: Gagal mengirim teks sebagai file: {e}", exc_info=True)

def find_sensible_split_point(text: str, max_len: int) -> int:
    if len(text) <= max_len: return len(text)
    slice_to_check = text[:max_len]
    split_point_newline_para = slice_to_check.rfind('\n\n')
    if split_point_newline_para != -1: return split_point_newline_para + 2 
    sentence_enders = ['. ', '! ', '? ', '.\n', '!\n', '?\n']
    best_split_point = -1
    for ender in sentence_enders:
        point = slice_to_check.rfind(ender)
        if point != -1 and point + len(ender) > best_split_point: best_split_point = point + len(ender)
    if best_split_point != -1: return best_split_point
    split_point_single_newline = slice_to_check.rfind('\n')
    if split_point_single_newline != -1: return split_point_single_newline + 1
    last_space = slice_to_check.rfind(' ')
    if last_space != -1: return last_space + 1
    return max_len

async def send_text_in_embeds(target_channel: discord.abc.Messageable, 
                              response_text: str, 
                              footer_text: str,
                              api_candidate_obj: genai_types.Candidate | None = None, # Untuk mengambil citation_metadata
                              reply_to_message: discord.Message | None = None,
                              interaction_to_followup: discord.Interaction | None = None,
                              is_direct_ai_response: bool = True, 
                              custom_title_prefix: str | None = None):
    embeds_to_send = []; remaining_text = response_text.strip()

    # --- PENANGANAN SITASI ---
    citations_field_value = None
    if api_candidate_obj and hasattr(api_candidate_obj, 'citation_metadata') and api_candidate_obj.citation_metadata and \
       hasattr(api_candidate_obj.citation_metadata, 'citations') and api_candidate_obj.citation_metadata.citations:
        citations_list = []
        for idx, citation in enumerate(api_candidate_obj.citation_metadata.citations[:3]): # Ambil maks 3
            title = getattr(citation, 'title', None)
            uri = getattr(citation, 'uri', None)
            if uri:
                display_name = title if title else (uri.split('/')[-1][:50] if '/' in uri else uri[:30])
                citations_list.append(f"{idx+1}. [{display_name.strip()[:50]}]({uri})")
        if citations_list:
            citations_field_value = "\n".join(citations_list)
    # -------------------------

    for i in range(2): 
        if not remaining_text and not (i == 0 and citations_field_value): # Jika tidak ada teks & bukan embed pertama dengan sitasi
             break
        current_embed_char_count = 0
        
        title_to_use = None
        if custom_title_prefix: 
            title_to_use = f"{custom_title_prefix} (Bagian {i+1})" if i > 0 or (len(response_text) > SAFE_CHAR_PER_EMBED and i==0) else custom_title_prefix
        elif not is_direct_ai_response: 
            title_to_use = f"Informasi (Bagian {i+1})" if i > 0 or (len(response_text) > SAFE_CHAR_PER_EMBED and i==0) else "Informasi"
        elif i > 0 or (len(response_text) > SAFE_CHAR_PER_EMBED and i==0) : 
            title_to_use = f"Lanjutan (Bagian {i+1})"
        
        embed = discord.Embed(title=title_to_use[:EMBED_TITLE_LIMIT] if title_to_use else None, color=discord.Color.random())
        if footer_text: embed.set_footer(text=footer_text[:2048])
        current_embed_char_count += len(embed.title or "") + len(embed.footer.text or "")
        
        # Isi deskripsi embed (hanya jika ada remaining_text)
        if remaining_text:
            available_desc_space = min(EMBED_DESC_LIMIT, SAFE_CHAR_PER_EMBED - current_embed_char_count - 50) 
            if citations_field_value and i == 0: # Sisakan ruang untuk field sitasi di embed pertama
                available_desc_space -= (len("Sumber Informasi:") + len(citations_field_value) + 50) # Perkiraan

            if available_desc_space > 0:
                desc_split_len = find_sensible_split_point(remaining_text, available_desc_space)
                if desc_split_len > 0:
                    embed.description = remaining_text[:desc_split_len]
                    remaining_text = remaining_text[desc_split_len:].lstrip()
                    current_embed_char_count += len(embed.description or "")
        
        # Isi fields jika masih ada teks dan kuota
        field_count = 0
        while remaining_text and field_count < (MAX_FIELDS_PER_EMBED - (1 if citations_field_value and i == 0 else 0)) and \
              current_embed_char_count < SAFE_CHAR_PER_EMBED:
            field_name = "..." 
            current_embed_char_count += len(field_name)
            available_field_space = min(EMBED_FIELD_VALUE_LIMIT, SAFE_CHAR_PER_EMBED - current_embed_char_count - 20) 
            if available_field_space <= 20: break 
            val_split_len = find_sensible_split_point(remaining_text, available_field_space)
            if val_split_len == 0 and remaining_text: val_split_len = min(len(remaining_text), available_field_space)
            field_value = remaining_text[:val_split_len]
            if not field_value.strip():
                if not remaining_text.strip(): break
                remaining_text = remaining_text[val_split_len:].lstrip(); continue
            embed.add_field(name=field_name, value=field_value, inline=False)
            remaining_text = remaining_text[val_split_len:].lstrip()
            current_embed_char_count += len(field_value); field_count += 1
        
        # Tambahkan field sitasi di embed pertama jika ada
        if i == 0 and citations_field_value and (embed.description or embed.fields or embed.title or remaining_text):
            if field_count < MAX_FIELDS_PER_EMBED and current_embed_char_count + len("Sumber Informasi:") + len(citations_field_value) < SAFE_CHAR_PER_EMBED:
                embed.add_field(name="Sumber Informasi:", value=citations_field_value[:EMBED_FIELD_VALUE_LIMIT], inline=False)
                current_embed_char_count += len("Sumber Informasi:") + len(citations_field_value)
            else: # Jika tidak muat, sitasi akan dikirim sebagai file bersama sisa teks
                if remaining_text: remaining_text = f"\n\nSumber Informasi:\n{citations_field_value}\n\n{remaining_text}"
                else: remaining_text = f"\n\nSumber Informasi:\n{citations_field_value}"
                _logger.info("AI_Utils: Sitasi tidak muat di embed pertama, akan digabung dengan sisa teks untuk file.")
        
        if embed.description or embed.fields or embed.title: 
            embeds_to_send.append(embed)
        elif not remaining_text: break # Tidak ada konten embed dan tidak ada sisa teks
        else: _logger.info(f"AI_Utils: Embed ke-{i+1} akan kosong, sisa teks ({len(remaining_text)} char) akan jadi file."); break 
    
    sent_first_message = False
    for idx, emb in enumerate(embeds_to_send):
        try:
            target_for_this_message = target_channel
            is_reply_this_time = False
            is_followup_this_time = False

            if idx == 0: 
                if interaction_to_followup:
                    target_for_this_message = interaction_to_followup
                    is_followup_this_time = True
                elif reply_to_message:
                    target_for_this_message = reply_to_message
                    is_reply_this_time = True
            
            if is_followup_this_time:
                if not target_for_this_message.response.is_done():
                    await target_for_this_message.response.send_message(embed=emb)
                else: await target_for_this_message.followup.send(embed=emb)
                sent_first_message = True
            elif is_reply_this_time:
                await target_for_this_message.reply(embed=emb); sent_first_message = True
            else: await target_channel.send(embed=emb)
            
            _logger.info(f"AI_Utils: Mengirim embed bagian {idx+1}.")
            if len(embeds_to_send) > 1: await asyncio.sleep(0.3)
        except discord.errors.HTTPException as e:
            _logger.error(f"AI_Utils: Gagal mengirim embed bagian {idx+1}: {e}", exc_info=True)
            failed_content = f"Title: {emb.title}\nDesc: {emb.description}\n" + "".join([f"\nFld ({f.name}):\n{f.value}\n" for f in emb.fields])
            await send_long_text_as_file(target_channel, failed_content, f"err_emb_{idx+1}.txt", "Gagal mengirim embed, kontennya sbg file:")
            if idx == 0 and remaining_text.strip(): await send_long_text_as_file(target_channel, remaining_text, "sisa_respons.txt", "Sisa (gagal embed):"); remaining_text = "" 
            break 
        except Exception as e_outer:
            _logger.error(f"AI_Utils: Error tak terduga saat mengirim embed {idx+1}: {e_outer}", exc_info=True)
            if idx == 0 and remaining_text.strip(): await send_long_text_as_file(target_channel, remaining_text, "sisa_respons_fatal.txt", "Sisa (setelah error fatal kirim embed):"); remaining_text = "" 
            break

    if remaining_text.strip(): 
        initial_msg_for_file = "Respons lanjutan (melebihi kapasitas embed):"
        # ... (logika pengiriman file dan pesan pengantar sama) ...
        if not sent_first_message and interaction_to_followup:
            try:
                if not interaction_to_followup.response.is_done(): await interaction_to_followup.response.send_message(initial_msg_for_file, ephemeral=True)
                else: await interaction_to_followup.followup.send(initial_msg_for_file, ephemeral=True)
                sent_first_message = True
            except Exception as e_fup: _logger.error(f"AI_Utils: Gagal kirim pesan pengantar file followup: {e_fup}")
        elif not sent_first_message and reply_to_message:
            try: await reply_to_message.reply(initial_msg_for_file); sent_first_message = True
            except Exception as e_rpl:
                _logger.error(f"AI_Utils: Gagal kirim pesan pengantar file reply: {e_rpl}")
                try: await target_channel.send(initial_msg_for_file); sent_first_message = True
                except Exception as e_ch: _logger.error(f"AI_Utils: Gagal kirim pesan pengantar file ke channel: {e_ch}")
        await send_long_text_as_file(target_channel, remaining_text, "respons_lanjutan.txt", initial_msg_for_file if sent_first_message else "Respons dari Noelle:")