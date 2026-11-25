import torch
from transformers import MusicgenForConditionalGeneration, MusicgenProcessor
import soundfile as sf
import hashlib
import os
import sys
import threading
import traceback
import random
from datetime import datetime
from fpdf import FPDF
import zipfile
import numpy as np
import customtkinter as ctk
import sounddevice as sd
from scipy.signal import butter, lfilter
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Рабочая папка
if getattr(sys, 'frozen', False):
    script_dir = os.path.dirname(sys.executable)
else:
    script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

# Тема
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Цветовая палитра Aegis Audio Premium
ACCENT = "#00E5FF"
ACCENT_HOVER = "#00B8D4"
ACCENT_GRADIENT = "#7C4DFF"
BG_APP = "#0A0A0F"
BG_CARD = "#15151F"
BG_CARD_HOVER = "#1E1E2E"
BG_SIDEBAR = "#0F0F18"
TEXT_PRIMARY = "#FFFFFF"
TEXT_DIM = "#6B7280"
TEXT_SUCCESS = "#10B981"
TEXT_WARNING = "#F59E0B"
TEXT_ERROR = "#EF4444"

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

RANDOM_PROMPTS = [
    "mysterious underwater exploration theme, deep sub-bass, echoing sonar pings, ethereal pads",
    "high-speed racing game soundtrack, adrenaline-pumping electronic rock, distorted guitars, fast tempo",
    "medieval fantasy tavern music, lute, flute, cheerful folk melody, acoustic instruments",
    "horror game ambient, unsettling drones, distant whispers, creaking sounds, psychological tension",
    "retro 8-bit platformer music, chiptune synths, upbeat melody, nostalgic video game feel",
    "jazz noir detective theme, smoky saxophone, upright bass, brushed drums, moody atmosphere",
    "epic boss battle music, powerful orchestral hits, choir chanting, dramatic brass fanfare",
    "peaceful meditation music, singing bowls, nature sounds, gentle wind chimes, zen atmosphere",
]


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

    def generate_chunk(self, prompt, duration, seed=None, temperature=1.0, guidance_scale=3.0):
        """Генерирует один чанк аудио с настройками"""
        inputs = self.processor(text=[prompt], padding=True, return_tensors="pt")
        
        if seed is not None:
            torch.manual_seed(seed)
            np.random.seed(seed)
        
        with torch.no_grad():
            audio_values = self.model.generate(
                **inputs, 
                max_new_tokens=int(duration * 50),
                do_sample=True,
                temperature=temperature,
                guidance_scale=guidance_scale,
            )
        
        audio = audio_values[0].cpu().numpy().squeeze(0)
        max_val = np.max(np.abs(audio))
        if max_val > 1.0:
            audio = audio / max_val
        return audio

    def generate(self, prompt, duration=10, seed=None, temperature=1.0, guidance_scale=3.0):
        """Генерирует аудио с расширенными настройками"""
        self.status("🎵 Генерация аудио...")
        
        CHUNK_DURATION = 30
        CROSSFADE_DURATION = 2
        
        if duration <= CHUNK_DURATION:
            self.progress(10)
            audio = self.generate_chunk(prompt, duration, seed, temperature, guidance_scale)
            self.progress(90)
            return audio
        else:
            num_chunks = int(np.ceil(duration / CHUNK_DURATION))
            chunks = []
            
            for i in range(num_chunks):
                self.progress(int((i / num_chunks) * 80) + 10)
                self.status(f"🎵 Генерация чанка {i+1}/{num_chunks}...")
                
                chunk_seed = (seed + i) if seed is not None else None
                chunk = self.generate_chunk(prompt, CHUNK_DURATION, chunk_seed, temperature, guidance_scale)
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
        peak = np.max(np.abs(audio))
        if peak > 0:
            audio = audio / peak * 0.95
            
        b, a = butter(4, 30 / (samplerate / 2), btype='highpass')
        audio = lfilter(b, a, audio)
        
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
        self.title("AEGIS AUDIO | Premium AI Generator")
        self.geometry("1000x900")
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
        self.track_count = 0
        self.history = []

        self._build_ui()
        threading.Thread(target=self._load_model, daemon=True).start()

    def _build_ui(self):
        self.configure(fg_color=BG_APP)

        # Главный контейнер с двумя колонками
        main_container = ctk.CTkFrame(self, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=20, pady=20)

        # Левая колонка (основной интерфейс)
        left_panel = ctk.CTkFrame(main_container, fg_color="transparent", width=650)
        left_panel.pack(side="left", fill="both", expand=True)

        # Правая колонка (история)
        right_panel = ctk.CTkFrame(main_container, fg_color=BG_SIDEBAR, width=300, corner_radius=16)
        right_panel.pack(side="right", fill="y", padx=(10, 0))

        # ===== ЛЕВАЯ ПАНЕЛЬ =====
        
        # Шапка
        header = ctk.CTkFrame(left_panel, fg_color=BG_CARD, corner_radius=16)
        header.pack(fill="x", pady=(0, 12))

        title_frame = ctk.CTkFrame(header, fg_color="transparent")
        title_frame.pack(fill="x", padx=20, pady=(16, 8))

        ctk.CTkLabel(
            title_frame,
            text="🛡️  AEGIS AUDIO",
            font=("Segoe UI", 28, "bold"),
            text_color=ACCENT,
        ).pack(side="left")

        # Счетчик треков
        self.counter_label = ctk.CTkLabel(
            title_frame,
            text="Треков: 0",
            font=("Segoe UI", 12),
            text_color=TEXT_DIM,
        )
        self.counter_label.pack(side="right", pady=8)

        ctk.CTkLabel(
            header,
            text="Royalty-free AI audio with built-in legal protection",
            font=("Segoe UI", 12),
            text_color=TEXT_DIM,
        ).pack(anchor="w", padx=20, pady=(0, 16))

        # Статус и прогресс
        status_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        status_frame.pack(fill="x", pady=(0, 8))

        self.status_label = ctk.CTkLabel(
            status_frame, text="Инициализация...",
            font=("Consolas", 11), text_color=TEXT_WARNING,
            anchor="w"
        )
        self.status_label.pack(fill="x")

        self.progress_bar = ctk.CTkProgressBar(left_panel, width=650, height=10, corner_radius=5)
        self.progress_bar.pack(pady=(0, 12))
        self.progress_bar.set(0)

        # Карточка "Промпт"
        card_prompt = ctk.CTkFrame(left_panel, fg_color=BG_CARD, corner_radius=16)
        card_prompt.pack(fill="x", pady=(0, 12))

        prompt_header = ctk.CTkFrame(card_prompt, fg_color="transparent")
        prompt_header.pack(fill="x", padx=20, pady=(16, 8))

        ctk.CTkLabel(
            prompt_header, text="ОПИСАНИЕ МУЗЫКИ",
            font=("Segoe UI", 11, "bold"), text_color=TEXT_DIM
        ).pack(side="left")

        # Кнопка случайного промпта
        random_btn = ctk.CTkButton(
            prompt_header, text="🎲 Случайный", width=120, height=28,
            corner_radius=14, fg_color=BG_CARD_HOVER, hover_color="#2A2A3E",
            font=("Segoe UI", 10),
            command=self._random_prompt
        )
        random_btn.pack(side="right")

        self.prompt_box = ctk.CTkTextbox(
            card_prompt, height=100, corner_radius=12,
            font=("Segoe UI", 13), wrap="word",
            fg_color=BG_CARD_HOVER
        )
        self.prompt_box.pack(fill="x", padx=20, pady=(0, 12))
        self.prompt_box.insert("1.0", "aggressive drill trap instrumental, distorted 808 sub-bass sliding notes, rapid triplet hi-hats rolls, dark minor key melody, crisp snare hits, high fidelity production, studio quality mix")

        # Пресеты
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

        # Карточка "Настройки"
        card_settings = ctk.CTkFrame(left_panel, fg_color=BG_CARD, corner_radius=16)
        card_settings.pack(fill="x", pady=(0, 12))

        # Длительность
        row1 = ctk.CTkFrame(card_settings, fg_color="transparent")
        row1.pack(fill="x", padx=20, pady=(16, 10))

        ctk.CTkLabel(row1, text="⏱️ Длительность:", font=("Segoe UI", 12)).pack(side="left")
        self.duration_slider = ctk.CTkSlider(
            row1, from_=5, to=120, number_of_steps=115, width=280,
            command=self._update_duration_label
        )
        self.duration_slider.set(10)
        self.duration_slider.pack(side="left", padx=12)
        self.duration_label = ctk.CTkLabel(
            row1, text="10 сек", font=("Segoe UI", 12, "bold"), text_color=ACCENT
        )
        self.duration_label.pack(side="left")

        # Temperature
        row2 = ctk.CTkFrame(card_settings, fg_color="transparent")
        row2.pack(fill="x", padx=20, pady=(0, 10))

        ctk.CTkLabel(row2, text="🎨 Креативность:", font=("Segoe UI", 12)).pack(side="left")
        self.temp_slider = ctk.CTkSlider(
            row2, from_=0.5, to=2.0, number_of_steps=15, width=280,
            command=self._update_temp_label
        )
        self.temp_slider.set(1.0)
        self.temp_slider.pack(side="left", padx=12)
        self.temp_label = ctk.CTkLabel(
            row2, text="1.0", font=("Segoe UI", 12, "bold"), text_color=ACCENT
        )
        self.temp_label.pack(side="left")

        # Guidance Scale
        row3 = ctk.CTkFrame(card_settings, fg_color="transparent")
        row3.pack(fill="x", padx=20, pady=(0, 10))

        ctk.CTkLabel(row3, text="🎯 Точность промпта:", font=("Segoe UI", 12)).pack(side="left")
        self.guidance_slider = ctk.CTkSlider(
            row3, from_=1.0, to=10.0, number_of_steps=18, width=280,
            command=self._update_guidance_label
        )
        self.guidance_slider.set(3.0)
        self.guidance_slider.pack(side="left", padx=12)
        self.guidance_label = ctk.CTkLabel(
            row3, text="3.0", font=("Segoe UI", 12, "bold"), text_color=ACCENT
        )
        self.guidance_label.pack(side="left")

        # Имя лицензиата и Seed
        row4 = ctk.CTkFrame(card_settings, fg_color="transparent")
        row4.pack(fill="x", padx=20, pady=(0, 10))

        ctk.CTkLabel(row4, text="👤 Лицензиат:", font=("Segoe UI", 12)).pack(side="left")
        self.user_entry = ctk.CTkEntry(
            row4, width=200, placeholder_text="User",
            fg_color=BG_CARD_HOVER
        )
        self.user_entry.pack(side="left", padx=12)

        self.seed_var = ctk.BooleanVar(value=False)
        self.seed_check = ctk.CTkCheckBox(
            row4, text="🎲 Фикс. seed",
            variable=self.seed_var,
            font=("Segoe UI", 11),
            fg_color=BG_CARD_HOVER
        )
        self.seed_check.pack(side="left", padx=(20, 0))

        self.seed_entry = ctk.CTkEntry(
            row4, width=100, placeholder_text="42",
            fg_color=BG_CARD_HOVER, state="disabled"
        )
        self.seed_entry.pack(side="left", padx=12)

        self.seed_var.trace("w", lambda *args: self._toggle_seed())

        # Кнопка GENERATE
        self.generate_btn = ctk.CTkButton(
            left_panel, text="⚡  GENERATE TRACK",
            height=60, corner_radius=16,
            font=("Segoe UI", 18, "bold"),
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color="#000000",
            command=self._on_generate
        )
        self.generate_btn.pack(fill="x", pady=(0, 12))

        # Визуализация волны
        self.waveframe = ctk.CTkFrame(left_panel, fg_color=BG_CARD, corner_radius=16, height=120)
        self.waveframe.pack(fill="x", pady=(0, 12))
        self.waveframe.pack_propagate(False)
        
        self.wave_label = ctk.CTkLabel(
            self.waveframe, text="Визуализация появится после генерации",
            font=("Segoe UI", 11), text_color=TEXT_DIM
        )
        self.wave_label.pack(expand=True)

        # Карточка результата
        self.result_card = ctk.CTkFrame(left_panel, fg_color=BG_CARD, corner_radius=16)
        self.result_card.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            self.result_card, text="РЕЗУЛЬТАТ",
            font=("Segoe UI", 11, "bold"), text_color=TEXT_DIM
        ).pack(anchor="w", padx=20, pady=(16, 8))

        self.result_text = ctk.CTkLabel(
            self.result_card,
            text="Пока пусто. Нажми GENERATE.",
            font=("Consolas", 11), text_color=TEXT_DIM,
            wraplength=600, justify="left"
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

        # ===== ПРАВАЯ ПАНЕЛЬ (ИСТОРИЯ) =====
        
        ctk.CTkLabel(
            right_panel, text="📜 ИСТОРИЯ",
            font=("Segoe UI", 14, "bold"), text_color=TEXT_PRIMARY
        ).pack(anchor="w", padx=20, pady=(16, 12))

        self.history_frame = ctk.CTkFrame(right_panel, fg_color="transparent")
        self.history_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.history_label = ctk.CTkLabel(
            self.history_frame, text="Здесь будут последние треки",
            font=("Segoe UI", 11), text_color=TEXT_DIM,
            wraplength=260
        )
        self.history_label.pack(expand=True)

    def _random_prompt(self):
        prompt = random.choice(RANDOM_PROMPTS)
        self._set_prompt(prompt)

    def _toggle_seed(self):
        if self.seed_var.get():
            self.seed_entry.configure(state="normal")
            self.seed_entry.delete(0, "end")
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

    def _update_temp_label(self, value):
        self.temp_label.configure(text=f"{float(value):.1f}")

    def _update_guidance_label(self, value):
        self.guidance_label.configure(text=f"{float(value):.1f}")

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
        temperature = float(self.temp_slider.get())
        guidance_scale = float(self.guidance_slider.get())
        
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
            args=(prompt, duration, user_name, seed, temperature, guidance_scale),
            daemon=True
        ).start()

    def _generate_worker(self, prompt, duration, user_name, seed, temperature, guidance_scale):
        try:
            audio = self.generator.generate(prompt, duration, seed, temperature, guidance_scale)
            self.current_audio = audio

            wav = self.generator.save_wav(audio)
            file_hash = self.generator.calculate_hash(wav)
            pdf = self.generator.generate_license_pdf(wav, file_hash, user_name)
            zip_file = self.generator.create_package(wav, pdf)

            self.track_count += 1

            duration_str = f"{duration // 60} мин {duration % 60} сек" if duration >= 60 else f"{duration} сек"
            info = (
                f"✅ Пакет: {zip_file}\n"
                f"⏱️ Длительность: {duration_str}\n"
                f"👤 Лицензиат: {user_name}\n"
                f"🎨 Temp: {temperature:.1f} | 🎯 Guidance: {guidance_scale:.1f}\n"
                f"🔐 SHA-256: {file_hash[:32]}...\n"
                f"📦 Размер: {os.path.getsize(zip_file) // 1024} КБ"
            )
            if seed is not None:
                info += f"\n🎲 Seed: {seed}"

            # Добавляем в историю
            history_entry = {
                "time": datetime.now().strftime("%H:%M"),
                "prompt": prompt[:50] + "..." if len(prompt) > 50 else prompt,
                "duration": duration_str,
                "file": zip_file
            }
            self.history.insert(0, history_entry)
            if len(self.history) > 5:
                self.history.pop()

            def done():
                self.result_text.configure(text=info, text_color=TEXT_PRIMARY)
                self.generate_btn.configure(state="normal", text="⚡  GENERATE TRACK")
                self.play_btn.configure(state="normal")
                self.open_btn.configure(state="normal")
                self.counter_label.configure(text=f"Треков: {self.track_count}")
                self.set_status("✓ Трек и лицензия готовы")
                self.set_progress(100)
                self._update_history()
                self._draw_waveform(audio)

            self.after(0, done)
        except Exception as e:
            def err():
                self.generate_btn.configure(state="normal", text="⚡  GENERATE TRACK")
                self.set_status(f"✗ Ошибка: {e}")
                print(traceback.format_exc())
            self.after(0, err)

    def _update_history(self):
        # Очищаем историю
        for widget in self.history_frame.winfo_children():
            widget.destroy()

        if not self.history:
            self.history_label.pack(expand=True)
            return

        for entry in self.history:
            item_frame = ctk.CTkFrame(self.history_frame, fg_color=BG_CARD_HOVER, corner_radius=10)
            item_frame.pack(fill="x", pady=(0, 6))

            ctk.CTkLabel(
                item_frame, text=f"🕐 {entry['time']}",
                font=("Segoe UI", 10), text_color=TEXT_DIM
            ).pack(anchor="w", padx=10, pady=(6, 0))

            ctk.CTkLabel(
                item_frame, text=entry['prompt'],
                font=("Segoe UI", 10), text_color=TEXT_PRIMARY,
                wraplength=240, justify="left"
            ).pack(anchor="w", padx=10, pady=(2, 0))

            ctk.CTkLabel(
                item_frame, text=f"⏱️ {entry['duration']}",
                font=("Segoe UI", 9), text_color=ACCENT
            ).pack(anchor="w", padx=10, pady=(2, 6))

    def _draw_waveform(self, audio):
        # Удаляем старый график
        for widget in self.waveframe.winfo_children():
            widget.destroy()

        # Создаем график
        fig, ax = plt.subplots(figsize=(6, 2), dpi=80)
        fig.patch.set_facecolor(BG_CARD)
        ax.set_facecolor(BG_CARD)

        # Рисуем волну
        ax.plot(audio, color=ACCENT, linewidth=0.5)
        ax.set_xlim(0, len(audio))
        ax.set_ylim(-1.1, 1.1)
        ax.axis('off')

        # Встраиваем в tkinter
        canvas = FigureCanvasTkAgg(fig, master=self.waveframe)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)

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
