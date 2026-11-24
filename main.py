import torch
from transformers import MusicgenForConditionalGeneration, MusicgenProcessor
import soundfile as sf
import hashlib
import os
from datetime import datetime
from fpdf import FPDF
import zipfile

class MusicLicenseGenerator:
    def __init__(self):
        print("Загрузка модели MusicGen... (это займет время при первом запуске)")
        self.processor = MusicgenProcessor.from_pretrained("facebook/musicgen-small")
        self.model = MusicgenForConditionalGeneration.from_pretrained("facebook/musicgen-small")
        self.model.eval()
        print("Модель загружена!")
    
    def generate_music(self, prompt, duration=10):
        """Генерирует музыку по текстовому описанию"""
        print(f"Генерация музыки: '{prompt}'...")
        
        inputs = self.processor(
            text=[prompt],
            padding=True,
            return_tensors="pt",
        )
        
        with torch.no_grad():
            audio_values = self.model.generate(**inputs, max_new_tokens=duration * 50)
        
        # Сохраняем аудио
        filename = f"track_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        sf.write(filename, audio_values[0].numpy(), samplerate=32000)
        
        return filename
    
    def calculate_hash(self, filepath):
        """Вычисляет SHA-256 хеш файла"""
        sha256_hash = hashlib.sha256()
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    def generate_license_pdf(self, audio_filename, file_hash, user_name="User"):
        """Создает PDF-сертификат лицензии"""
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        
        # Заголовок
        pdf.set_font("Arial", "B", 16)
        pdf.cell(200, 10, txt="COMMERCIAL MUSIC LICENSE CERTIFICATE", ln=True, align="C")
        pdf.ln(10)
        
        # Основная информация
        pdf.set_font("Arial", size=12)
        pdf.cell(200, 10, txt=f"License Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=True)
        pdf.cell(200, 10, txt=f"License Holder: {user_name}", ln=True)
        pdf.cell(200, 10, txt=f"Audio File: {audio_filename}", ln=True)
        pdf.cell(200, 10, txt=f"File Hash (SHA-256): {file_hash}", ln=True)
        pdf.ln(10)
        
        # Текст лицензии
        pdf.set_font("Arial", "B", 14)
        pdf.cell(200, 10, txt="LICENSE TERMS:", ln=True)
        pdf.ln(5)
        
        pdf.set_font("Arial", size=11)
        license_text = """This certificate grants the License Holder a perpetual, worldwide, 
non-exclusive, royalty-free license to use the specified audio file for any commercial 
purpose, including but not limited to: video games, films, advertisements, streaming 
content, and other media projects.

The audio file was generated using AI technology trained exclusively on open-source 
and public domain datasets. The License Holder is free to modify, distribute, and 
monetize this audio file without any restrictions or attribution requirements.

This license is tied to the specific file hash above and cannot be transferred to 
other files."""
        
        pdf.multi_cell(0, 6, license_text)
        
        # Сохраняем PDF
        pdf_filename = f"license_{audio_filename.replace('.wav', '.pdf')}"
        pdf.output(pdf_filename)
        
        return pdf_filename
    
    def create_package(self, audio_filename, pdf_filename):
        """Упаковывает аудио и лицензию в ZIP"""
        zip_filename = f"
