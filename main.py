import torch
from transformers import MusicgenForConditionalGeneration, MusicgenProcessor
import soundfile as sf
import hashlib
import os
import sys
import threading
import queue
import traceback
from datetime import datetime
from fpdf import FPDF
import zipfile
import numpy as np
import customtkinter as ctk
import sounddevice as sd

# Рабочая папка = папка скрипта (важно для EXE)
if getattr(sys, 'frozen', False):
    # Если запущено как EXE
    script_dir = os.path.dirname(sys.executable)
else:
    script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

# Тема и цвета
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

ACCENT = "#7C4DFF"
ACCENT_HOVER = "#651FFF"
BG_CARD = "#242424"
TEXT_DIM = "#9E9E9E"

PRESETS = {
    "Synthwave": "dark synthwave chase scene, heavy bass, 120 bpm, retro analog synths",
    "Cyberpunk": "cyberpunk industrial techno, distorted bass, glitchy percussion",
    "Epic Orchestral": "epic cinematic orchestral trailer music, brass, choir, timpani",
    "Lo-fi Chill": "lo-fi hip hop beat, warm vinyl crackle, mellow piano, chill",
    "Trap": "modern trap beat, 808 bass, hi-hats, dark melodic piano",
    "Ambient": "ambient space drone, ethereal pads, slow evolving textures",
}


class MusicLicenseGenerator:
    def __init__(self, status_callback=None):
        self.status = status_callback or (lambda x: None)
        self.processor = None
        self.model = None

    def load(self):
        self.status("Загрузка модели (~2 ГБ, первый раз качается)...")
        self.processor = MusicgenProcessor.from_pretrained("facebook/musicgen-small")
        self.model = MusicgenForConditionalGeneration.from_pretrained("facebook/musicgen-small")
        self.model.eval()
        self.status("Модель готова")

    def generate(self, prompt, duration=10):
        self.status("Генерация аудио...")
        inputs = self.processor(text=[prompt], padding=True, return_tensors="pt")
        with torch.no_grad():
            audio_values = self.model.generate(**inputs, max_new_tokens=duration * 50)
        audio = audio_values[0].cpu().numpy().squeeze(0)
        max_val = np.max(np.abs(audio))
        if max_val > 1.0:
            audio = audio / max_val
        return audio

    @staticmethod
    def save_wav(audio, samplerate=32000):
        filename = f"track_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        sf.write(filename, audio, samplerate=samplerate, subtype='PCM_16')
        return filename

    @staticmethod
    def calculate_hash(filepath):
        sha256_hash = hashlib.sha256()
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    @staticmethod
    def generate_license_pdf(audio_filename, file_hash, user_name):
        pdf = FPDF()
        pdf.add_page()
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

    @staticmethod
    def create_package(audio_filename, pdf_filename):
        zip_filename = f"music_package_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        with zipfile.ZipFile(zip_filename, 'w') as zipf:
            zipf.write(audio_filename)
            zipf.write(pdf_filename)
        os.remove(audio_filename)
        os.remove(pdf_filename)
        return zip_filename


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("MUSIC LICENSE GENERATOR")
        self.geometry("720x820")
        self.resizable(False, False)

        self.generator = MusicLicenseGenerator(status_callback=self.set_status)
        self.model_loaded = False
        self.current_audio = None
        self.current_sr = 32000
        self.is_playing = False
        self.last_package = None

        self._build_ui()

        # Загружаем модель в фоне
        threading.Thread(target=self._load_model, daemon=True).start()

    # ---------- UI ----------
    def _build_ui(self):
        # Шапка
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(20, 8))

        ctk.CTkLabel(
            header,
            text="MUSIC LICENSE GENERATOR",
            font=("Segoe UI", 22, "bold"),
            text_color=ACCENT,
        ).pack(anchor="w")

        ctk.CTkLabel(
            header,
            text="Royalty-free AI audio for game developers & creators",
            font=("Segoe UI", 12),
            text_color=TEXT_DIM,
        ).pack(anchor="w")

        # Статус-бар
        self.status_label = ctk.CTkLabel(
            self, text="Инициализация...",
            font=("Consolas", 11), text_color="#FFB74D"
        )
        self.status_label.pack(fill="x", padx=24, pady=(0, 12))

        # Карточка "Промпт"
        card_prompt = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=14)
        card_prompt.pack(fill="x", padx=24, pady=(0, 12))

        ctk.CTkLabel(
            card_prompt, text="ОПИСАНИЕ МУЗЫКИ",
            font=("Segoe UI", 11, "bold"), text_color=TEXT_DIM
        ).pack(anchor="w", padx=16, pady=(14, 6))

        self.prompt_box = ctk.CTkTextbox(
            card_prompt, height=90, corner_radius=10,
            font=("Segoe UI", 13), wrap="word"
        )
        self.prompt_box.pack(fill="x", padx=16, pady=(0, 10))
        self.prompt_box.insert("1.0", "dark synthwave chase scene, heavy bass, 120 bpm")

        # Пресеты (чипы)
        chips_frame = ctk.CTkFrame(card_prompt, fg_color="transparent")
        chips_frame.pack(fill="x", padx=16, pady=(0, 14))

        for name, text in PRESETS.items():
            chip = ctk.CTkButton(
                chips_frame, text=name, width=90, height=28,
                corner_radius=14, fg_color="#333333", hover_color="#444444",
                font=("Segoe UI", 11),
                command=lambda t=text: self._set_prompt(t)
            )
            chip.pack(side="left", padx=(0, 6))

        # Карточка "Настройки"
        card_settings = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=14)
        card_settings.pack(fill="x", padx=24, pady=(0, 12))

        # Длительность
        row1 = ctk.CTkFrame(card_settings, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=(14, 6))

        ctk.CTkLabel(row1, text="Длительность:", font=("Segoe UI", 12)).pack(side="left")
        self.duration_slider = ctk.CTkSlider(
            row1, from_=5, to=30, number_of_steps=25, width=320,
            command=self._update_duration_label
        )
        self.duration_slider.set(10)
        self.duration_slider.pack(side="left", padx=12)
        self.duration_label = ctk.CTkLabel(row1, text="10 сек", font=("Segoe UI", 12, "bold"), text_color=ACCENT)
        self.duration_label.pack(side="left")

        # Имя лицензиата
        row2 = ctk.CTkFrame(card_settings, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=(6, 14))

        ctk.CTkLabel(row2, text="Имя лицензиата:", font=("Segoe UI", 12)).pack(side="left")
        self.user_entry = ctk.CTkEntry(row2, width=260, placeholder_text="User")
        self.user_entry.pack(side="left", padx=12)

        # Кнопка GENERATE
        self.generate_btn = ctk.CTkButton(
            self, text="⚡  GENERATE TRACK",
            height=52, corner_radius=12,
            font=("Segoe UI", 16, "bold"),
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            command=self._on_generate
        )
        self.generate_btn.pack(fill="x", padx=24, pady=(0, 12))

        # Карточка результата
        self.result_card = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=14)
        self.result_card.pack(fill="x", padx=24, pady=(0, 16))

        ctk.CTkLabel(
            self.result_card, text="РЕЗУЛЬТАТ",
            font=("Segoe UI", 11, "bold"), text_color=TEXT_DIM
        ).pack(anchor="w", padx=16, pady=(14, 6))

        self.result_text = ctk.CTkLabel(
            self.result_card,
            text="Пока пусто. Нажми GENERATE.",
            font=("Consolas", 11), text_color=TEXT_DIM,
            wraplength=640, justify="left"
        )
        self.result_text.pack(anchor="w", padx=16, pady=(0, 10))

        # Кнопки управления результатом
        btn_row = ctk.CTkFrame(self.result_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 14))

        self.play_btn = ctk.CTkButton(
            btn_row, text="▶  Play", width=110, height=34,
            corner_radius=10, fg_color="#333333", hover_color="#444444",
            command=self._toggle_play, state="disabled"
        )
        self.play_btn.pack(side="left", padx=(0, 8))

        self.open_btn = ctk.CTkButton(
            btn_row, text="📂  Открыть папку", width=160, height=34,
            corner_radius=10, fg_color="#333333", hover_color="#444444",
            command=self._open_folder, state="disabled"
        )
        self.open_btn.pack(side="left")

    # ---------- Логика ----------
    def _set_prompt(self, text):
        self.prompt_box.delete("1.0", "end")
        self.prompt_box.insert("1.0", text)

    def _update_duration_label(self, value):
        self.duration_label.configure(text=f"{int(value)} сек")

    def set_status(self, msg):
        self.status_label.configure(text=msg)

    def _load_model(self):
        try:
            self.generator.load()
            self.model_loaded = True
            self.after(0, lambda: self.set_status("✓ Готов к работе"))
        except Exception as e:
            self.after(0, lambda: self.set_status(f"✗ Ошибка загрузки: {e}"))

    def _on_generate(self):
        if not self.model_loaded:
            self.set_status("⚠ Модель ещё грузится, подожди...")
            return

        prompt = self.prompt_box.get("1.0", "end").strip()
        if not prompt:
            self.set_status("⚠ Введи описание музыки")
            return

        duration = int(self.duration_slider.get())
        user_name = self.user_entry.get().strip() or "User"

        self.generate_btn.configure(state="disabled", text="ГЕНЕРАЦИЯ...")
        self.play_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")

        threading.Thread(
            target=self._generate_worker,
            args=(prompt, duration, user_name),
            daemon=True
        ).start()

    def _generate_worker(self, prompt, duration, user_name):
        try:
            audio = self.generator.generate(prompt, duration)
            self.current_audio = audio

            wav = self.generator.save_wav(audio)
            file_hash = self.generator.calculate_hash(wav)
            pdf = self.generator.generate_license_pdf(wav, file_hash, user_name)
            zip_file = self.generator.create_package(wav, pdf)
            self.last_package = zip_file

            info = (
                f"Файл: {zip_file}\n"
                f"Лицензиат: {user_name}\n"
                f"SHA-256: {file_hash[:32]}...\n"
                f"Размер: {os.path.getsize(zip_file) // 1024} КБ"
            )

            def done():
                self.result_text.configure(text=info, text_color="#FFFFFF")
                self.generate_btn.configure(state="normal", text="⚡  GENERATE TRACK")
                self.play_btn.configure(state="normal")
                self.open_btn.configure(state="normal")
                self.set_status("✓ Трек и лицензия готовы")

            self.after(0, done)
        except Exception as e:
            def err():
                self.generate_btn.configure(state="normal", text="⚡  GENERATE TRACK")
                self.set_status(f"✗ Ошибка: {e}")
                print(traceback.format_exc())
            self.after(0, err)

    def _toggle_play(self):
        if self.current_audio is None:
            return
        if self.is_playing:
            sd.stop()
            self.is_playing = False
            self.play_btn.configure(text="▶  Play")
        else:
            sd.play(self.current_audio, self.current_sr)
            self.is_playing = True
            self.play_btn.configure(text="■  Stop")

    def _open_folder(self):
        os.startfile(script_dir)


if __name__ == "__main__":
    app = App()
    app.mainloop()
