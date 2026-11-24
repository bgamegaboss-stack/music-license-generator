import torch
from transformers import MusicgenForConditionalGeneration, MusicgenProcessor
import hashlib
import os
import sys
from datetime import datetime
from fpdf import FPDF
import zipfile
import traceback
import numpy as np

# Пытаемся импортировать soundfile, если не получится - используем scipy
try:
    import soundfile as sf
    HAS_SOUNDFILE = True
except:
    HAS_SOUNDFILE = False
    from scipy.io import wavfile

# ВАЖНО: переключаем рабочую папку на ту, где лежит этот скрипт
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

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
        
        # Правильно извлекаем аудио
        # MusicGen возвращает форму (batch, channels, samples)
        audio = audio_values[0].cpu().numpy()
        
        # Убираем размерность канала - делаем моно
        if audio.ndim > 1:
            audio = audio.squeeze(0)
        
        print(f"Форма аудио: {audio.shape}")
        print(f"Диапазон значений: от {audio.min():.4f} до {audio.max():.4f}")
        
        # Нормализуем в диапазон -1.0 ... 1.0 если нужно
        max_val = np.max(np.abs(audio))
        if max_val > 1.0:
            audio = audio / max_val
            print(f"Аудио нормализовано, новый максимум: {np.max(np.abs(audio)):.4f}")
        
        # Сохраняем аудио
        filename = f"track_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        
        if HAS_SOUNDFILE:
            sf.write(filename, audio, samplerate=32000, subtype='PCM_16')
        else:
            # Fallback на scipy - конвертируем в int16
            audio_int16 = (audio * 32767).astype(np.int16)
            wavfile.write(filename, 32000, audio_int16)
        
        file_size = os.path.getsize(filename)
        print(f"Файл сохранен: {filename}")
        print(f"Размер файла: {file_size} байт ({file_size / 1024 / 1024:.2f} МБ)")
        
        if file_size < 1000:
            print("ВНИМАНИЕ: файл слишком маленький, возможно проблема с записью!")
        
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
        
        pdf.set_font("Arial", "B", 16)
        pdf.cell(200, 10, txt="COMMERCIAL MUSIC LICENSE CERTIFICATE", ln=True, align="C")
        pdf.ln(10)
        
        pdf.set_font("Arial", size=12)
        pdf.cell(200, 10, txt=f"License Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=True)
        pdf.cell(200, 10, txt=f"License Holder: {user_name}", ln=True)
        pdf.cell(200, 10, txt=f"Audio File: {audio_filename}", ln=True)
        pdf.cell(200, 10, txt=f"File Hash (SHA-256): {file_hash}", ln=True)
        pdf.ln(10)
        
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
        
        pdf_filename = f"license_{audio_filename.replace('.wav', '.pdf')}"
        pdf.output(pdf_filename)
        
        return pdf_filename
    
    def create_package(self, audio_filename, pdf_filename):
        """Упаковывает аудио и лицензию в ZIP"""
        zip_filename = f"music_package_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        
        with zipfile.ZipFile(zip_filename, 'w') as zipf:
            zipf.write(audio_filename)
            zipf.write(pdf_filename)
        
        os.remove(audio_filename)
        os.remove(pdf_filename)
        
        return zip_filename

def main():
    print("=" * 60)
    print("MUSIC LICENSE GENERATOR - MVP")
    print("=" * 60)
    
    current_dir = os.getcwd()
    print(f"\nРабочая папка: {current_dir}")
    print("=" * 60)
    
    generator = MusicLicenseGenerator()
    
    prompt = input("\nВведите описание музыки (например, 'epic cyberpunk chase music'): ")
    duration = int(input("Длительность в секундах (рекомендуется 10-30): ") or "10")
    user_name = input("Имя пользователя для лицензии (или нажмите Enter для 'User'): ") or "User"
    
    print("\nГенерация...")
    
    audio_file = generator.generate_music(prompt, duration)
    print(f"Аудио создано: {audio_file}")
    
    file_hash = generator.calculate_hash(audio_file)
    print(f"Хеш файла: {file_hash}")
    
    pdf_file = generator.generate_license_pdf(audio_file, file_hash, user_name)
    print(f"Лицензия создана: {pdf_file}")
    
    zip_package = generator.create_package(audio_file, pdf_file)
    
    print("\n" + "=" * 60)
    print(f"ГОТОВО! Пакет создан: {zip_package}")
    print("Внутри: аудиофайл + PDF-сертификат лицензии")
    print(f"\nВсе файлы находятся в папке: {current_dir}")
    print("=" * 60)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("\n" + "=" * 60)
        print("ОШИБКА!")
        print("=" * 60)
        print(traceback.format_exc())

input("\nНажмите Enter для выхода...")
