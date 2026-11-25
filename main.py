import torch
from transformers import MusicgenForConditionalGeneration, MusicgenProcessor
import soundfile as sf
import hashlib
import os
import sys
import threading
import traceback
from datetime import datetime
from fpdf import FPDF
import zipfile
import numpy as np
import customtkinter as ctk
import sounddevice as sd
from scipy.signal import butter, lfilter

# Рабочая папка
if getattr(sys, 'frozen', False):
    script_dir = os.path.dirname(sys.executable)
else:
    script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

# Тема
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Цветовая палитра Aegis Audio
ACCENT = "#00E5FF"
ACCENT_HOVER = "#00B8D4"
BG_APP = "#0A0A0F"
BG_CARD = "#15151F"
BG_CARD_HOVER = "#1E1E2E"
TEXT_PRIMARY = "#FFFFFF"
TEXT_DIM = "#6B7280"
TEXT_WARNING = "#F59E0B"

PRESETS = {
    "Synthwave": "dark synthwave chase scene, heavy bass, 120 bpm, retro analog synths",
    "Cyberpunk": "cyberpunk industrial techno, distorted bass, glitchy percussion",
    "Epic Orchestral": "epic cinematic orchestral trailer music, brass, choir, timpani",
    "Lo-fi Chill": "lo-fi hip hop beat, warm vinyl crackle, mellow piano, chill",
    "Trap": "aggressive drill trap instrumental, distorted 808 sub-bass sliding notes, rapid triplet hi-hats rolls, dark minor key melody, crisp snare hits, high fidelity production, studio quality mix",
    "Ambient": "ambient space drone, ethereal pads, slow evolving textures",
    "Dark Cinematic": "dark cinematic tension, low strings, ominous atmosphere",
    "Electronic": "upbeat electronic dance music, energetic synths, driving beat",
}


class MusicLicenseGenerator:
    def __init__(self, status_callback=None, progress_callback=None):
        self.status = status_callback or (lambda x: None)
        self.progress = progress_callback or (lambda x: None)
        self.processor = None
        self.model = None

    def load(self):
        self.status("⏳ Загрузка модели (~2 ГБ, только первый раз)...")
        self.processor = MusicgenProcessor.from_pretrained("facebook/musicgen-small")
        self.model = MusicgenForConditionalGeneration.from_pretrained("facebook/musicgen-small")
        self.model.eval()
        self.status("✓ Модель готова")

    def generate_chunk(self, prompt, duration, seed=None):
        """Генерирует один чанк аудио"""
        inputs = self.processor(text=[prompt], padding=True, return_tensors="pt")
        
        if seed is not None:
            torch.manual_seed(seed)
            np.random.seed(seed)
        
        with torch.no_grad():
            audio_values = self.model.generate(
                **inputs, 
                max_new_tokens=int(duration * 50),
                do_sample=True,
                temperature=1.0,
            )
        
        audio = audio_values[0].cpu().numpy().squeeze(0)
        max_val = np.max(np.abs(audio))
        if max_val > 1.0:
            audio = audio / max_val
        return audio

    def generate(self, prompt, duration=10, seed=None):
        """Генерирует аудио, для длинных треков использует чанки"""
        self.status("🎵 Генерация аудио...")
        
        CHUNK_DURATION = 15
        CROSSFADE_DURATION = 2
        
        if duration <= CHUNK_DURATION:
            self.progress(10)
            audio = self.generate_chunk(prompt, duration, seed)
            self.progress(90)
            return audio
        else:
            num_chunks = int(np.ceil(duration / CHUNK_DURATION))
            chunks = []
            
            for i in range(num_chunks):
                self.progress(int((i / num_chunks) * 80) + 10)
                self.status(f"🎵 Генерация чанка {i+1}/{num_chunks}...")
                
                chunk_seed = (seed + i) if seed is not None else None
                chunk = self.generate_chunk(prompt, CHUNK_DURATION, chunk_seed)
                chunks.append(chunk)
            
            self.status("🔗 Склейка чанков...")
            self.progress(90)
            
            sample_rate = 32000
            crossfade_samples = int(CROSSFADE_DURATION * sample_rate)
            
            result = chunks[0]
            for i in range(1, len(chunks)):
                fade_out = np.linspace(1.0, 0.0, crossfade_samples)
                fade_in = np.linspace(0.0, 1.0, crossfade_samples)
                
                result_end = result[-crossfade_samples:] * fade_out
                chunk_start = chunks[i][:crossfade_samples] * fade_in
                
                result = np.concatenate([
                    result[:-crossfade_samples],
                    result_end + chunk_start,
                    chunks[i][crossfade_samples:]
                ])
            
            target_samples = int(duration * sample_rate)
            if len(result) > target_samples:
                result = result[:target_samples]
            
            return result

    @staticmethod
    def save_wav(audio, samplerate=32000):
        # 1. Нормализация громкости (Peak Normalization)
        peak = np.max(np.abs(audio))
        if peak > 0:
            audio = audio / peak * 0.95
            
        # 2. High-Pass Filter (убираем низкочастотный гул ниже 30Hz)
        b, a = butter(4, 30 / (samplerate / 2), btype='highpass')
        audio = lfilter(b, a, audio)
        
        # 3. Soft Clipping (делает звук плотнее, убирает резкие цифровые искажения)
        audio = np.tanh(audio * 1.3) / np.tanh(1.3)
        
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
        pdf.set_font("Arial", "B", 18)
        pdf.cell(200, 12, txt="AEGIS AUDIO", ln=True, align="C")
        pdf.set_font("Arial", size=12)
        pdf.cell(200, 8, txt="Commercial License Certificate", ln=True, align="C")
        pdf.ln(12)
        pdf.set_font("Arial", size=11)
        pdf.cell(200, 8, txt=f"License Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=True)
        pdf.cell(200, 8, txt=f"License Holder: {user_name}", ln=True)
        pdf.cell(200, 8, txt=f"Audio File: {audio_filename}", ln=True)
        pdf.cell(200, 8, txt=f"File Hash (SHA-256):", ln=True)
        pdf.set_font("Courier", size=9)
        pdf.multi_cell(0, 5, file_hash)
        pdf.ln(8)
        pdf.set_font("Arial", "B", 13)
        pdf.cell(200, 10, txt="LICENSE TERMS:", ln=True)
        pdf.ln(4)
        pdf.set_font("Arial", size=10)
        license_text = """This certificate grants the License Holder a perpetual, worldwide,
non-exclusive, royalty-free license to use the specified audio file for any commercial
purpose, including but not limited to: video games, films, advertisements, streaming
content, and other media projects.

The audio file was generated using AI technology trained exclusively on open-source
and public domain datasets. The License Holder is free to modify, distribute, and
monetize this audio file without any restrictions or attribution requirements.

This license is tied to the specific file hash above and cannot be transferred to
other files.

Issued by: Aegis Audio"""
        pdf.multi_cell(0, 5, license_text)
        pdf_filename = f"license_{audio_filename.replace('.wav', '.pdf')}"
        pdf.output(pdf_filename)
        return pdf_filename

    @staticmethod
    def create_package(audio_filename, pdf_filename):
        zip_filename = f"AegisAudio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        with zipfile.ZipFile(zip_filename, 'w') as zipf:
            zipf.write(audio_filename)
            zipf.write(pdf_filename)
        os.remove(audio_filename)
        os.remove(pdf_filename)
        return zip_filename


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("AEGIS AUDIO | Royalty-Free AI Generator")
        self.geometry("760x900")
        self.resizable(False, False)

        try:
            self.iconbitmap("app.ico")
        except:
            pass

        self.generator = MusicLicenseGenerator(
            status_callback=self.set_status,
            progress_callback=self.set_progress
        )
        self.model_loaded = False
        self.current_audio = None
        self.current_sr = 32000
        self.is_playing = False

        self._build_ui()
        threading.Thread(target=self._load_model, daemon=True).start()

    def _build_ui(self):
        self.configure(fg_color=BG_APP)

        header = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0)
        header.pack(fill="x")

        ctk.CTkLabel(
            header,
            text="🛡️  AEGIS AUDIO",
            font=("Segoe UI", 26, "bold"),
            text_color=ACCENT,
        ).pack(anchor="w", padx=24, pady=(16, 4))

        ctk.CTkLabel(
            header,
            text="Royalty-free AI audio with built-in legal protection",
            font=("Segoe UI", 12),
            text_color=TEXT_DIM,
        ).pack(anchor="w", padx=24, pady=(0, 16))

        status_frame = ctk.CTkFrame(self, fg_color="transparent")
        status_frame.pack(fill="x", padx=24, pady=(16, 8))

        self.status_label = ctk.CTkLabel(
            status_frame, text="Инициализация...",
            font=("Consolas", 11), text_color=TEXT_WARNING,
            anchor="w"
        )
        self.status_label.pack(fill="x")

        self.progress_bar = ctk.CTkProgressBar(self, width=712, height=8)
        self.progress_bar.pack(padx=24, pady=(0, 12))
        self.progress_bar.set(0)

        card_prompt = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=16)
        card_prompt.pack(fill="x", padx=24, pady=(0, 12))

        ctk.CTkLabel(
            card_prompt, text="ОПИСАНИЕ МУЗЫКИ",
            font=("Segoe UI", 11, "bold"), text_color=TEXT_DIM
        ).pack(anchor="w", padx=20, pady=(16, 8))

        self.prompt_box = ctk.CTkTextbox(
            card_prompt, height=100, corner_radius=12,
            font=("Segoe UI", 13), wrap="word",
            fg_color=BG_CARD_HOVER
        )
        self.prompt_box.pack(fill="x", padx=20, pady=(0, 12))
        self.prompt_box.insert("1.0", "aggressive drill trap instrumental, distorted 808 sub-bass sliding notes, rapid triplet hi-hats rolls, dark minor key melody, crisp snare hits, high fidelity production, studio quality mix")

        chips_frame = ctk.CTkFrame(card_prompt, fg_color="transparent")
        chips_frame.pack(fill="x", padx=20, pady=(0, 16))

        for name, text in PRESETS.items():
            chip = ctk.CTkButton(
                chips_frame, text=name, width=100, height=30,
                corner_radius=15, fg_color=BG_CARD_HOVER, hover_color="#2A2A3E",
                font=("Segoe UI", 11),
                command=lambda t=text: self._set_prompt(t)
            )
            chip.pack(side="left", padx=(0, 6))

        card_settings = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=16)
        card_settings.pack(fill="x", padx=24, pady=(0, 12))

        row1 = ctk.CTkFrame(card_settings, fg_color="transparent")
        row1.pack(fill="x", padx=20, pady=(16, 10))

        ctk.CTkLabel(row1, text="Длительность:", font=("Segoe UI", 12)).pack(side="left")
        self.duration_slider = ctk.CTkSlider(
            row1, from_=5, to=120, number_of_steps=115, width=340,
            command=self._update_duration_label
        )
        self.duration_slider.set(10)
        self.duration_slider.pack(side="left", padx=12)
        self.duration_label = ctk.CTkLabel(
            row1, text="10 сек", font=("Segoe UI", 12, "bold"), text_color=ACCENT
        )
        self.duration_label.pack(side="left")

        row2 = ctk.CTkFrame(card_settings, fg_color="transparent")
        row2.pack(fill="x", padx=20, pady=(0, 10))

        ctk.CTkLabel(row2, text="Имя лицензиата:", font=("Segoe UI", 12)).pack(side="left")
        self.user_entry = ctk.CTkEntry(
            row2, width=260, placeholder_text="User",
            fg_color=BG_CARD_HOVER
        )
        self.user_entry.pack(side="left", padx=12)

        row3 = ctk.CTkFrame(card_settings, fg_color="transparent")
        row3.pack(fill="x", padx=20, pady=(0, 16))

        self.seed_var = ctk.BooleanVar(value=False)
        self.seed_check = ctk.CTkCheckBox(
            row3, text="Фиксированный seed",
            variable=self.seed_var,
            font=("Segoe UI", 11),
            fg_color=BG_CARD_HOVER
        )
        self.seed_check.pack(side="left")

        self.seed_entry = ctk.CTkEntry(
            row3, width=120, placeholder_text="Seed (число)",
            fg_color=BG_CARD_HOVER, state="disabled"
        )
        self.seed_entry.pack(side="left", padx=12)

        self.seed_var.trace("w", lambda *args: self._toggle_seed())

        self.generate_btn = ctk.CTkButton(
            self, text="⚡  GENERATE TRACK",
            height=56, corner_radius=14,
            font=("Segoe UI", 16, "bold"),
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color="#000000",
            command=self._on_generate
        )
        self.generate_btn.pack(fill="x", padx=24, pady=(0, 12))

        self.result_card = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=16)
        self.result_card.pack(fill="x", padx=24, pady=(0, 20))

        ctk.CTkLabel(
            self.result_card, text="РЕЗУЛЬТАТ",
            font=("Segoe UI", 11, "bold"), text_color=TEXT_DIM
        ).pack(anchor="w", padx=20, pady=(16, 8))

        self.result_text = ctk.CTkLabel(
            self.result_card,
            text="Пока пусто. Нажми GENERATE.",
            font=("Consolas", 11), text_color=TEXT_DIM,
            wraplength=680, justify="left"
        )
        self.result_text.pack(anchor="w", padx=20, pady=(0, 12))

        btn_row = ctk.CTkFrame(self.result_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 16))

        self.play_btn = ctk.CTkButton(
            btn_row, text="▶  Play", width=120, height=36,
            corner_radius=12, fg_color=BG_CARD_HOVER, hover_color="#2A2A3E",
            command=self._toggle_play, state="disabled"
        )
        self.play_btn.pack(side="left", padx=(0, 10))

        self.open_btn = ctk.CTkButton(
            btn_row, text="📂  Открыть папку", width=170, height=36,
            corner_radius=12, fg_color=BG_CARD_HOVER, hover_color="#2A2A3E",
            command=self._open_folder, state="disabled"
        )
        self.open_btn.pack(side="left")

    def _toggle_seed(self):
        if self.seed_var.get():
            self.seed_entry.configure(state="normal")
            self.seed_entry.insert(0, "42")
        else:
            self.seed_entry.configure(state="disabled")
            self.seed_entry.delete(0, "end")

    def _set_prompt(self, text):
        self.prompt_box.delete("1.0", "end")
        self.prompt_box.insert("1.0", text)

    def _update_duration_label(self, value):
        val = int(value)
        if val >= 60:
            mins = val // 60
            secs = val % 60
            self.duration_label.configure(text=f"{mins} мин {secs} сек")
        else:
            self.duration_label.configure(text=f"{val} сек")

    def set_status(self, msg):
        self.status_label.configure(text=msg)

    def set_progress(self, value):
        self.progress_bar.set(value / 100)

    def _load_model(self):
        try:
            self.generator.load()
            self.model_loaded = True
            self.after(0, lambda: self.set_status("✓ Готов к работе"))
            self.after(0, lambda: self.set_progress(100))
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
        
        seed = None
        if self.seed_var.get():
            try:
                seed = int(self.seed_entry.get())
            except:
                self.set_status("⚠ Seed должен быть числом")
                return

        self.generate_btn.configure(state="disabled", text="ГЕНЕРАЦИЯ...")
        self.play_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.set_progress(0)

        threading.Thread(
            target=self._generate_worker,
            args=(prompt, duration, user_name, seed),
            daemon=True
        ).start()

    def _generate_worker(self, prompt, duration, user_name, seed):
        try:
            audio = self.generator.generate(prompt, duration, seed)
            self.current_audio = audio

            wav = self.generator.save_wav(audio)
            file_hash = self.generator.calculate_hash(wav)
            pdf = self.generator.generate_license_pdf(wav, file_hash, user_name)
            zip_file = self.generator.create_package(wav, pdf)

            duration_str = f"{duration // 60} мин {duration % 60} сек" if duration >= 60 else f"{duration} сек"
            info = (
                f"✅ Пакет: {zip_file}\n"
                f"⏱️ Длительность: {duration_str}\n"
                f"👤 Лицензиат: {user_name}\n"
                f"🔐 SHA-256: {file_hash[:32]}...\n"
                f"📦 Размер: {os.path.getsize(zip_file) // 1024} КБ"
            )
            if seed is not None:
                info += f"\n🎲 Seed: {seed}"

            def done():
                self.result_text.configure(text=info, text_color=TEXT_PRIMARY)
                self.generate_btn.configure(state="normal", text="⚡  GENERATE TRACK")
                self.play_btn.configure(state="normal")
                self.open_btn.configure(state="normal")
                self.set_status("✓ Трек и лицензия готовы")
                self.set_progress(100)

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
