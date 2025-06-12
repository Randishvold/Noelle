# Noelle_Bot/utils/logging_config.py
import os
import sys
import logging
import datetime
import pathlib

def setup_logging():
    """
    Mengonfigurasi logging untuk menulis ke file log per sesi di folder 'logs'
    dan juga menampilkan log di konsol.
    """
    # Tentukan path root proyek agar folder 'logs' dibuat di tempat yang benar
    # Ini penting jika script dijalankan dari direktori yang berbeda.
    project_root = pathlib.Path(__file__).resolve().parent.parent
    log_dir = project_root / "logs"
    
    # 1. Buat folder 'logs' jika belum ada
    os.makedirs(log_dir, exist_ok=True)

    # 2. Buat nama file log yang unik berdasarkan waktu startup
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_filename = log_dir / f"noelle_{timestamp}.log"

    # 3. Dapatkan root logger.
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO) # Set level dasar

    # 4. Hapus handler yang sudah ada (jika ada, untuk mencegah duplikasi)
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # 5. Buat formatter untuk mendefinisikan format log
    log_formatter = logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s')

    # 6. Buat File Handler untuk menulis ke file
    file_handler = logging.FileHandler(log_filename, encoding='utf-8')
    file_handler.setFormatter(log_formatter)
    root_logger.addHandler(file_handler)

    # 7. Buat Stream Handler untuk tetap menampilkan log di konsol
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)
    root_logger.addHandler(console_handler)
    
    logging.info("Logging berhasil dikonfigurasi. Log akan disimpan di: %s", log_filename)