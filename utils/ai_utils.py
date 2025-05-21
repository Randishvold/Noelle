# Noelle_AI_Bot/utils/ai_utils.py
import discord
import io
import asyncio
import logging

_logger = logging.getLogger(__name__) # Logger spesifik untuk utilitas AI

async def send_long_text_as_file(target_channel: discord.abc.Messageable, text_content: str, filename: str = "response.txt", initial_message: str = "Respons terlalu panjang, dikirim sebagai file:"):
    """Mengirim teks panjang sebagai file ke channel yang ditentukan."""
    try:
        file_data = io.BytesIO(text_content.encode('utf-8'))
        discord_file = discord.File(fp=file_data, filename=filename)
        await target_channel.send(content=initial_message, file=discord_file)
        _logger.info(f"Mengirim respons panjang sebagai file '{filename}' ke channel {target_channel.id}.")
    except Exception as e:
        _logger.error(f"Gagal mengirim teks sebagai file ke channel {target_channel.id}: {e}", exc_info=True)

def find_sensible_split_point(text: str, max_len: int) -> int:
    """Mencari titik potong yang "masuk akal" dalam batas max_len."""
    if len(text) <= max_len: return len(text)
    slice_to_check = text[:max_len]
    split_point_newline = slice_to_check.rfind('\n\n')
    if split_point_newline != -1: return split_point_newline + 2 
    sentence_enders = ['. ', '! ', '? ', '.\n', '!\n', '?\n'] # Tambahkan variasi dengan newline
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
                              title_prefix: str, 
                              footer_text: str,
                              reply_to_message: discord.Message | None = None,
                              interaction_to_followup: discord.Interaction | None = None):
    """Mengirim teks dalam maksimal 2 embed. Sisa dikirim sebagai file."""
    EMBED_TITLE_LIMIT = 256; EMBED_DESC_LIMIT = 4096; EMBED_FIELD_VALUE_LIMIT = 1024
    MAX_FIELDS_PER_EMBED = 25; SAFE_CHAR_PER_EMBED = 5800 
    embeds_to_send = []; remaining_text = response_text.strip()

    for i in range(2): # Maksimal 2 embed
        if not remaining_text: break
        current_embed_char_count = 0
        title = f"{title_prefix} (Bagian {i+1})" if i > 0 or (len(response_text) > SAFE_CHAR_PER_EMBED and i==0) else title_prefix
        embed = discord.Embed(title=title[:EMBED_TITLE_LIMIT], color=discord.Color.random())
        if footer_text: embed.set_footer(text=footer_text)
        current_embed_char_count += len(embed.title or "") + len(embed.footer.text or "")
        
        available_desc_space = min(EMBED_DESC_LIMIT, SAFE_CHAR_PER_EMBED - current_embed_char_count - 50) # buffer
        if available_desc_space > 0:
            desc_split_len = find_sensible_split_point(remaining_text, available_desc_space)
            if desc_split_len > 0:
                embed.description = remaining_text[:desc_split_len]
                remaining_text = remaining_text[desc_split_len:].lstrip()
                current_embed_char_count += len(embed.description or "")
        
        field_count = 0
        while remaining_text and field_count < MAX_FIELDS_PER_EMBED and current_embed_char_count < SAFE_CHAR_PER_EMBED:
            field_name = "Lanjutan..."
            current_embed_char_count += len(field_name)
            available_field_space = min(EMBED_FIELD_VALUE_LIMIT, SAFE_CHAR_PER_EMBED - current_embed_char_count - 20) # buffer
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
        
        if embed.description or embed.fields: embeds_to_send.append(embed)
        elif not remaining_text: break
        else: _logger.info(f"Embed ke-{i+1} akan kosong, sisa teks akan dikirim sebagai file."); break 
    
    for idx, emb in enumerate(embeds_to_send):
        try:
            if idx == 0: 
                if interaction_to_followup: await interaction_to_followup.followup.send(embed=emb)
                elif reply_to_message: await reply_to_message.reply(embed=emb)
                else: await target_channel.send(embed=emb)
            else: await target_channel.send(embed=emb)
            _logger.info(f"Utils: Mengirim embed bagian {idx+1}.")
            await asyncio.sleep(0.3)
        except discord.errors.HTTPException as e:
            _logger.error(f"Utils: Gagal mengirim embed bagian {idx+1}: {e}", exc_info=True)
            failed_content = f"Title: {emb.title}\nDesc: {emb.description}\n" + "".join([f"\nFld ({f.name}):\n{f.value}\n" for f in emb.fields])
            await send_long_text_as_file(target_channel, failed_content, f"err_emb_{idx+1}.txt", "Gagal mengirim embed, kontennya sbg file:")
            if idx == 0 and remaining_text.strip(): await send_long_text_as_file(target_channel, remaining_text, "sisa_respons.txt", "Sisa (gagal embed):"); remaining_text = "" 
            break 
    if remaining_text.strip(): await send_long_text_as_file(target_channel, remaining_text, "respons_lanjutan.txt", "Respons lanjutan (melebihi embed):")