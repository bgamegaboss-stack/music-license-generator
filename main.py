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

# ===== DARK THEME WITH WHITE ISLAND =====
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Цветовая палитра
BG_APP = "#000000"
BG_CARD = "#1A1A1A"
BG_CARD_HOVER = "#2A2A2A"
BORDER = "#333333"

ISLAND_BG = "#FFFFFF"
ISLAND_TEXT = "#000000"
ISLAND_DIM = "#666666"

ACCENT = "#007AFF"
ACCENT_HOVER = "#0066CC"
ACCENT_LIGHT = "#E5F1FF"

SUCCESS = "#34C759"
WARNING = "#FF9500"
DANGER = "#FF3B30"

TEXT_PRIMARY = "#FFFFFF"
TEXT_SECONDARY = "#A0A0A0"
TEXT_DIM = "#666666"

SAMPLE_RATE = 32000
NATIVE_CHUNK = 30
CONTEXT_TAIL = 10
CROSSFADE = 2

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

# Библиотека звуковых эффектов (категории)
SOUND_LIBRARY = {
    "Басы": [
        "deep 808 sub-bass, heavy low-end, rumbling",
        "distorted bass guitar, aggressive low frequencies",
        "synth bass, smooth analog warmth, pulsing",
    ],
    "Ударные": [
        "crisp trap hi-hats, rapid triplet rolls, sharp",
        "powerful kick drum, punchy, tight",
        "snare hits, crisp, reverb tail",
    ],
    "Атмосфера": [
        "ethereal pads, dreamy, floating",
        "dark ambient drone, ominous, tension",
        "vinyl crackle, warm, nostalgic",
    ],
    "Эффекты": [
        "riser effect, building tension, white noise sweep",
        "impact hit, cinematic boom, dramatic",
        "glitch effects, digital artifacts, stutter",
    ],
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
        self.status("Загрузка модели (~2 ГБ, только первый раз)...")
        self.processor = MusicgenProcessor.from_pretrained("facebook/musicgen-small")
        self.model = MusicgenForConditionalGeneration.from_pretrained("facebook/musicgen-small")
        self.model.eval()
        self.status("Модель готова")

    def _generate_with_context(self, prompt, duration, audio_context=None,
                               seed=None, temperature=1.0, guidance_scale=3.0):
        if audio_context is not None:
            ctx = torch.from_numpy(audio_context).float().unsqueeze(0)
            inputs = self.processor(
                text=[prompt],
                audio=ctx,
                sampling_rate=SAMPLE_RATE,
                return_tensors="pt",
                padding=True,
            )
        else:
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

    @staticmethod
    def _blend_with_crossfade(result, new_chunk, crossfade_samples):
        fade_out = np.linspace(1.0, 0.0, crossfade_samples)
        fade_in = np.linspace(0.0, 1.0, crossfade_samples)

        tail = result[-crossfade_samples:] * fade_out
        head = new_chunk[:crossfade_samples] * fade_in
        blended = tail + head

        return np.concatenate([
            result[:-crossfade_samples],
            blended,
            new_chunk[crossfade_samples:]
        ])

    def generate(self, prompt, duration=10, seed=None,
                 temperature=1.0, guidance_scale=3.0):
        self.status("Генерация аудио...")

        if duration <= NATIVE_CHUNK:
            self.progress(15)
            audio = self._generate_with_context(
                prompt, duration, None, seed, temperature, guidance_scale
            )
            self.progress(95)
            return audio

        self.progress(15)
        self.status("Генерация: начало мелодии...")
        result = self._generate_with_context(
            prompt, NATIVE_CHUNK, None, seed, temperature, guidance_scale
        )

        remaining = duration - NATIVE_CHUNK
        step = 0
        while remaining > 0:
            step += 1
            chunk_len = min(remaining, NATIVE_CHUNK - CONTEXT_TAIL)
            if chunk_len < 3:
                chunk_len = remaining

            self.status(f"Продолжение мелодии... шаг {step}")
            self.progress(int(15 + (step / (step + remaining / 20)) * 70))

            ctx_samples = CONTEXT_TAIL * SAMPLE_RATE
            if len(result) < ctx_samples:
                ctx_samples = len(result)
            audio_context = result[-ctx_samples:]

            new_chunk = self._generate_with_context(
                prompt, chunk_len, audio_context,
                (seed + step) if seed is not None else None,
                temperature, guidance_scale
            )

            crossfade_samples = min(CROSSFADE * SAMPLE_RATE, len(result), len(new_chunk))
            result = self._blend_with_crossfade(result, new_chunk, crossfade_samples)

            remaining -= (chunk_len - CROSSFADE)

        target_samples = int(duration * SAMPLE_RATE)
        if len(result) > target_samples:
            result = result[:target_samples]

        self.progress(95)
        return result

    @staticmethod
    def save_wav(audio, samplerate=SAMPLE_RATE):
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


class DynamicIsland(ctk.CTkFrame):
    """Dynamic Island - чёрный островок, который расширяется в белую панель."""
    def __init__(self, master, app_instance, **kwargs):
        super().__init__(master, fg_color="#000000", corner_radius=20, height=40, **kwargs)
        self.app = app_instance
        self.is_expanded = False
        self.pack(fill="x", pady=(10, 0))
        
        # Маленький индикатор
        self.indicator = ctk.CTkLabel(
            self, text="●", font=("Segoe UI", 16), text_color="#FFFFFF"
        )
        self.indicator.pack(expand=True)
        
        # Клик для расширения
        self.bind("<Button-1>", self._toggle)
        self.indicator.bind("<Button-1>", self._toggle)
        
        # Большая панель (скрыта по умолчанию)
        self.expanded_panel = None

    def _toggle(self, event=None):
        if self.is_expanded:
            self._collapse()
        else:
            self._expand()

    def _expand(self):
        self.is_expanded = True
        self.configure(height=500, fg_color=ISLAND_BG, corner_radius=20)
        self.indicator.pack_forget()
        
        # Создаём расширенную панель
        self.expanded_panel = ctk.CTkFrame(self, fg_color="transparent")
        self.expanded_panel.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Заголовок
        header = ctk.CTkFrame(self.expanded_panel, fg_color="transparent")
        header.pack(fill="x", pady=(0, 15))
        
        ctk.CTkLabel(
            header, text="ИИ-Ассистент",
            font=("Segoe UI Variable Display", 20, "bold"),
            text_color=ISLAND_TEXT
        ).pack(side="left")
        
        ctk.CTkButton(
            header, text="✕", width=30, height=30,
            corner_radius=15, fg_color=BG_CARD_HOVER, hover_color=BG_CARD,
            text_color=ISLAND_TEXT, font=("Segoe UI", 14),
            command=self._collapse
        ).pack(side="right")
        
        # Чат с ассистентом
        chat_frame = ctk.CTkFrame(self.expanded_panel, fg_color=BG_CARD, corner_radius=12)
        chat_frame.pack(fill="both", expand=True, pady=(0, 10))
        
        self.chat_display = ctk.CTkTextbox(
            chat_frame, height=200, corner_radius=12,
            font=("Segoe UI", 12), wrap="word",
            fg_color=BG_CARD, text_color=ISLAND_TEXT
        )
        self.chat_display.pack(fill="both", expand=True, padx=10, pady=10)
        self.chat_display.insert("1.0", "Привет! Я твой ИИ-ассистент. Напиши команду:\n• 'обрежь до 20 секунд'\n• 'добавь fade in'\n• 'сделай громче на 50%'\n• 'библиотека звуков'\n")
        
        # Поле ввода
        input_frame = ctk.CTkFrame(self.expanded_panel, fg_color="transparent")
        input_frame.pack(fill="x")
        
        self.chat_input = ctk.CTkEntry(
            input_frame, placeholder_text="Напиши команду...",
            fg_color=BG_CARD, border_color=BORDER, border_width=1,
            corner_radius=10, text_color=ISLAND_TEXT
        )
        self.chat_input.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        ctk.CTkButton(
            input_frame, text="Отправить", width=100, height=36,
            corner_radius=10, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color="#FFFFFF", font=("Segoe UI", 12),
            command=self._process_command
        ).pack(side="right")
        
        # Кнопка возврата
        ctk.CTkButton(
            self, text="Свернуть", height=30,
            corner_radius=10, fg_color=BG_CARD_HOVER, hover_color=BG_CARD,
            text_color=ISLAND_TEXT, font=("Segoe UI", 11),
            command=self._collapse
        ).pack(pady=(10, 0))

    def _collapse(self):
        self.is_expanded = False
        self.configure(height=40, fg_color="#000000")
        if self.expanded_panel:
            self.expanded_panel.destroy()
            self.expanded_panel = None
        self.indicator.pack(expand=True)

    def _process_command(self):
        command = self.chat_input.get().strip().lower()
        if not command:
            return
        
        self.chat_input.delete(0, "end")
        self.chat_display.insert("end", f"\nТы: {command}\n")
        
        # Обработка команд
        response = self._handle_command(command)
        self.chat_display.insert("end", f"Ассистент: {response}\n")
        self.chat_display.see("end")

    def _handle_command(self, command):
        if not self.app.current_audio:
            return "Сначала сгенерируй трек."
        
        if "обрежь" in command or "trim" in command:
            # Извлекаем число секунд
            import re
            match = re.search(r'(\d+)', command)
            if match:
                seconds = int(match.group(1))
                samples = seconds * SAMPLE_RATE
                if len(self.app.current_audio) > samples:
                    self.app.current_audio = self.app.current_audio[:samples]
                    return f"✅ Обрезано до {seconds} секунд."
                else:
                    return f"Трек уже короче {seconds} секунд."
            return "Не понял длительность. Напиши 'обрежь до 20 секунд'."
        
        elif "fade in" in command or "фейд ин" in command:
            fade_samples = int(2 * SAMPLE_RATE)  # 2 секунды
            fade_in = np.linspace(0.0, 1.0, fade_samples)
            if len(self.app.current_audio) > fade_samples:
                self.app.current_audio[:fade_samples] *= fade_in
                return "✅ Fade in добавлен (2 сек)."
            return "Трек слишком короткий."
        
        elif "fade out" in command or "фейд аут" in command:
            fade_samples = int(2 * SAMPLE_RATE)
            fade_out = np.linspace(1.0, 0.0, fade_samples)
            if len(self.app.current_audio) > fade_samples:
                self.app.current_audio[-fade_samples:] *= fade_out
                return "✅ Fade out добавлен (2 сек)."
            return "Трек слишком короткий."
        
        elif "громче" in command or "louder" in command:
            match = re.search(r'(\d+)', command)
            if match:
                percent = int(match.group(1)) / 100.0
                self.app.current_audio *= (1.0 + percent)
                peak = np.max(np.abs(self.app.current_audio))
                if peak > 1.0:
                    self.app.current_audio /= peak
                return f"✅ Громкость увеличена на {percent*100:.0f}%."
            return "Напиши 'сделай громче на 50%'."
        
        elif "библиотека" in command or "звуки" in command:
            return "Библиотека звуков:\n• Басы: 808, synth bass\n• Ударные: hi-hats, kick, snare\n• Атмосфера: pads, drone\n• Эффекты: riser, impact, glitch\n\nНапиши 'добавь басы' или 'добавь ударные'."
        
        elif "басы" in command or "bass" in command:
            return "🎵 Генерация басовой линии... (это займёт время). Используй основной генератор с промптом 'deep 808 sub-bass'."
        
        else:
            return "Не понял команду. Попробуй: 'обрежь до 20 сек', 'добавь fade in', 'сделай громче на 50%'."


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Aegis Audio")
        self.geometry("1020x920")
        self.resizable(True, True)
        self.configure(fg_color=BG_APP)
        self.is_fullscreen = False

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
        self.is_playing = False
        self.track_count = 0
        self.history = []
        self._pulse_state = False
        self._wave_fig = None
        self._wave_ax = None
        self._wave_canvas = None

        self._build_ui()

        self.after(300, self._pulse_status)

        threading.Thread(target=self._load_model, daemon=True).start()

    def _build_ui(self):
        # Dynamic Island сверху
        self.island = DynamicIsland(self, self)

        # Главный контейнер
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=24, pady=24)

        left = ctk.CTkFrame(main, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True)

        right = ctk.CTkFrame(main, fg_color=BG_CARD, corner_radius=22,
                             border_color=BORDER, border_width=1, width=300)
        right.pack(side="right", fill="y", padx=(16, 0))
        right.pack_propagate(False)

        # ===== ШАПКА =====
        header = ctk.CTkFrame(left, fg_color=BG_CARD, corner_radius=22,
                              border_color=BORDER, border_width=1)
        header.pack(fill="x", pady=(0, 14))

        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.pack(fill="x", padx=22, pady=(18, 6))

        ctk.CTkLabel(
            title_row, text="Aegis Audio",
            font=("Segoe UI Variable Display", 30, "bold"),
            text_color=TEXT_PRIMARY
        ).pack(side="left")

        # Кнопка fullscreen
        self.fs_btn = ctk.CTkButton(
            title_row, text="⛶", width=40, height=30,
            corner_radius=8, fg_color=BG_CARD_HOVER, hover_color=BORDER,
            text_color=TEXT_PRIMARY, font=("Segoe UI", 14),
            command=self._toggle_fullscreen
        )
        self.fs_btn.pack(side="right", padx=(0, 10))

        self.counter_label = ctk.CTkLabel(
            title_row, text="0 треков",
            font=("Segoe UI", 12),
            text_color=TEXT_DIM
        )
        self.counter_label.pack(side="right", pady=6)

        ctk.CTkLabel(
            header,
            text="Royalty-free AI audio with cryptographic licensing",
            font=("Segoe UI", 13),
            text_color=TEXT_DIM
        ).pack(anchor="w", padx=22, pady=(0, 18))

        # ===== СТАТУС + ПРОГРЕСС =====
        status_card = ctk.CTkFrame(left, fg_color=BG_CARD, corner_radius=22,
                                   border_color=BORDER, border_width=1)
        status_card.pack(fill="x", pady=(0, 14))

        self.status_label = ctk.CTkLabel(
            status_card, text="Инициализация...",
            font=("Consolas", 12), text_color=WARNING,
            anchor="w"
        )
        self.status_label.pack(fill="x", padx=22, pady=(14, 8))

        self.progress_bar = ctk.CTkProgressBar(
            status_card, height=6, corner_radius=3,
            progress_color=ACCENT, fg_color=BORDER
        )
        self.progress_bar.pack(fill="x", padx=22, pady=(0, 14))
        self.progress_bar.set(0)

        # ===== ПРОМПТ =====
        prompt_card = ctk.CTkFrame(left, fg_color=BG_CARD, corner_radius=22,
                                   border_color=BORDER, border_width=1)
        prompt_card.pack(fill="x", pady=(0, 14))

        prompt_header = ctk.CTkFrame(prompt_card, fg_color="transparent")
        prompt_header.pack(fill="x", padx=22, pady=(16, 8))

        ctk.CTkLabel(
            prompt_header, text="ОПИСАНИЕ",
            font=("Segoe UI", 11, "bold"), text_color=TEXT_DIM
        ).pack(side="left")

        ctk.CTkButton(
            prompt_header, text="Случайный", width=110, height=28,
            corner_radius=14,
            font=("Segoe UI", 11),
            fg_color=ACCENT_LIGHT, hover_color=ACCENT_HOVER,
            text_color=ACCENT,
            command=self._random_prompt
        ).pack(side="right")

        self.prompt_box = ctk.CTkTextbox(
            prompt_card, height=92, corner_radius=14,
            font=("Segoe UI", 13), wrap="word",
            fg_color=BG_CARD_HOVER, border_color=BORDER, border_width=1
        )
        self.prompt_box.pack(fill="x", padx=22, pady=(0, 10))
        self.prompt_box.insert("1.0", PRESETS["Trap"])

        chips_frame = ctk.CTkFrame(prompt_card, fg_color="transparent")
        chips_frame.pack(fill="x", padx=22, pady=(0, 18))

        for name, text in PRESETS.items():
            ctk.CTkButton(
                chips_frame, text=name, width=100, height=30,
                corner_radius=15,
                fg_color=BG_CARD_HOVER, hover_color=BORDER,
                text_color=TEXT_SECONDARY,
                font=("Segoe UI", 11),
                command=lambda t=text: self._set_prompt(t)
            ).pack(side="left", padx=(0, 6))

        # ===== НАСТРОЙКИ =====
        settings_card = ctk.CTkFrame(left, fg_color=BG_CARD, corner_radius=22,
                                     border_color=BORDER, border_width=1)
        settings_card.pack(fill="x", pady=(0, 14))

        self._add_slider_row(
            settings_card, "Длительность",
            5, 120, 10, self._update_duration_label
        )
        self.duration_slider = settings_card._last_slider
        self.duration_label = settings_card._last_value_label

        self._add_slider_row(
            settings_card, "Креативность",
            0.5, 2.0, 1.0, self._update_temp_label
        )
        self.temp_slider = settings_card._last_slider
        self.temp_label = settings_card._last_value_label

        self._add_slider_row(
            settings_card, "Точность промпта",
            1.0, 10.0, 3.0, self._update_guidance_label
        )
        self.guidance_slider = settings_card._last_slider
        self.guidance_label = settings_card._last_value_label

        row = ctk.CTkFrame(settings_card, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=(0, 18))

        ctk.CTkLabel(row, text="Лицензиат", font=("Segoe UI", 12)).pack(side="left")
        self.user_entry = ctk.CTkEntry(
            row, width=200, placeholder_text="User",
            fg_color=BG_CARD_HOVER, border_color=BORDER, border_width=1,
            corner_radius=10
        )
        self.user_entry.pack(side="left", padx=12)

        self.seed_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            row, text="Фикс. seed", variable=self.seed_var,
            font=("Segoe UI", 11),
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            checkmark_color="#FFFFFF",
            border_color=BORDER
        ).pack(side="left", padx=(20, 0))
        self.seed_var.trace("w", lambda *a: self._toggle_seed())

        self.seed_entry = ctk.CTkEntry(
            row, width=90, placeholder_text="42",
            fg_color=BG_CARD_HOVER, border_color=BORDER, border_width=1,
            corner_radius=10, state="disabled"
        )
        self.seed_entry.pack(side="left", padx=10)

        # ===== КНОПКА GENERATE =====
        self.generate_btn = ctk.CTkButton(
            left, text="Сгенерировать трек",
            height=58, corner_radius=18,
            font=("Segoe UI Variable Display", 17, "bold"),
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color="#FFFFFF",
            command=self._on_generate
        )
        self.generate_btn.pack(fill="x", pady=(0, 14))

        # ===== ВОЛНА =====
        self.wave_card = ctk.CTkFrame(left, fg_color=BG_CARD, corner_radius=22,
                                      border_color=BORDER, border_width=1, height=130)
        self.wave_card.pack(fill="x", pady=(0, 14))
        self.wave_card.pack_propagate(False)

        self.wave_placeholder = ctk.CTkLabel(
            self.wave_card, text="Визуализация волны появится после генерации",
            font=("Segoe UI", 12), text_color=TEXT_DIM
        )
        self.wave_placeholder.pack(expand=True)

        # ===== РЕЗУЛЬТАТ =====
        result_card = ctk.CTkFrame(left, fg_color=BG_CARD, corner_radius=22,
                                   border_color=BORDER, border_width=1)
        result_card.pack(fill="x")

        ctk.CTkLabel(
            result_card, text="РЕЗУЛЬТАТ",
            font=("Segoe UI", 11, "bold"), text_color=TEXT_DIM
        ).pack(anchor="w", padx=22, pady=(16, 8))

        self.result_text = ctk.CTkLabel(
            result_card,
            text="Пока пусто. Нажми «Сгенерировать трек».",
            font=("Consolas", 11), text_color=TEXT_DIM,
            wraplength=640, justify="left"
        )
        self.result_text.pack(anchor="w", padx=22, pady=(0, 10))

        btn_row = ctk.CTkFrame(result_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=22, pady=(0, 18))

        self.play_btn = ctk.CTkButton(
            btn_row, text="Play", width=110, height=36,
            corner_radius=12,
            fg_color=BG_CARD_HOVER, hover_color=BORDER,
            text_color=ACCENT, font=("Segoe UI", 12),
            command=self._toggle_play, state="disabled"
        )
        self.play_btn.pack(side="left", padx=(0, 8))

        self.open_btn = ctk.CTkButton(
            btn_row, text="Открыть папку", width=150, height=36,
            corner_radius=12,
            fg_color=BG_CARD_HOVER, hover_color=BORDER,
            text_color=ACCENT, font=("Segoe UI", 12),
            command=self._open_folder, state="disabled"
        )
        self.open_btn.pack(side="left")

        # ===== ИСТОРИЯ =====
        ctk.CTkLabel(
            right, text="История",
            font=("Segoe UI Variable Display", 18, "bold"),
            text_color=TEXT_PRIMARY
        ).pack(anchor="w", padx=20, pady=(20, 14))

        self.history_scroll = ctk.CTkScrollableFrame(
            right, fg_color="transparent",
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=BG_CARD_HOVER
        )
        self.history_scroll.pack(fill="both", expand=True, padx=12, pady=(0, 14))

        self.history_empty = ctk.CTkLabel(
            self.history_scroll,
            text="Здесь появятся\nпоследние треки",
            font=("Segoe UI", 12), text_color=TEXT_DIM,
            justify="center"
        )
        self.history_empty.pack(expand=True, pady=40)

    def _toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        if self.is_fullscreen:
            self.attributes("-fullscreen", True)
            self.fs_btn.configure(text="✕")
        else:
            self.attributes("-fullscreen", False)
            self.fs_btn.configure(text="⛶")

    def _add_slider_row(self, parent, label, from_, to, default, update_fn):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=(14, 6))

        ctk.CTkLabel(row, text=label, font=("Segoe UI", 12),
                     text_color=TEXT_SECONDARY).pack(side="left")

        slider = ctk.CTkSlider(
            row, from_=from_, to=to, width=280,
            command=update_fn,
            progress_color=ACCENT,
            fg_color=BORDER,
            button_color=TEXT_PRIMARY,
            button_hover_color=BG_CARD_HOVER,
            button_length=24,
        )
        slider.set(default)
        slider.pack(side="left", padx=14)

        value_label = ctk.CTkLabel(row, text="", font=("Segoe UI", 12, "bold"),
                                   text_color=ACCENT)
        value_label.pack(side="left")

        parent._last_slider = slider
        parent._last_value_label = value_label

    def _pulse_status(self):
        if self.model_loaded:
            return
        self._pulse_state = not self._pulse_state
        color = ACCENT if self._pulse_state else WARNING
        current = self.status_label.cget("text")
        if "Инициализация" in current or "Загрузка" in current:
            self.status_label.configure(text_color=color)
        self.after(700, self._pulse_status)

    def _animate_wave(self, audio):
        if self._wave_fig is None:
            return
        total_steps = 15
        step_size = max(1, len(audio) // total_steps)

        def draw_step(step):
            if self._wave_fig is None:
                return
            end = min((step + 1) * step_size, len(audio))
            data = audio[:end]
            self._wave_ax.clear()
            self._wave_ax.set_facecolor(BG_CARD)
            self._wave_ax.plot(data, color=ACCENT, linewidth=0.8)
            self._wave_ax.set_xlim(0, len(audio))
            self._wave_ax.set_ylim(-1.1, 1.1)
            self._wave_ax.axis('off')
            self._wave_canvas.draw_idle()
            if step < total_steps - 1:
                self.after(40, lambda: draw_step(step + 1))

        draw_step(0)

    def _random_prompt(self):
        self._set_prompt(random.choice(RANDOM_PROMPTS))

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
            self.duration_label.configure(text=f"{val//60}:{val%60:02d}")
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
            self.after(0, lambda: self.set_status("Готов к работе"))
            self.after(0, lambda: self.set_progress(100))
            self.after(0, lambda: self.status_label.configure(text_color=SUCCESS))
        except Exception as e:
            self.after(0, lambda: self.set_status(f"Ошибка: {e}"))
            self.after(0, lambda: self.status_label.configure(text_color=DANGER))

    def _on_generate(self):
        if not self.model_loaded:
            self.set_status("Модель ещё грузится...")
            return

        prompt = self.prompt_box.get("1.0", "end").strip()
        if not prompt:
            self.set_status("Введи описание музыки")
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
                self.set_status("Seed должен быть числом")
                return

        self.generate_btn.configure(state="disabled", text="Генерация...")
        self.play_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.set_progress(0)
        self.status_label.configure(text_color=ACCENT)

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

            dur_str = f"{duration//60}:{duration%60:02d}" if duration >= 60 else f"{duration} сек"
            info = (
                f"Файл: {zip_file}\n"
                f"Длительность: {dur_str}\n"
                f"Лицензиат: {user_name}\n"
                f"Temp: {temperature:.1f}  |  Guidance: {guidance_scale:.1f}\n"
                f"SHA-256: {file_hash[:32]}...\n"
                f"Размер: {os.path.getsize(zip_file) // 1024} КБ"
            )
            if seed is not None:
                info += f"\nSeed: {seed}"

            self.history.insert(0, {
                "time": datetime.now().strftime("%H:%M"),
                "prompt": prompt[:60] + "..." if len(prompt) > 60 else prompt,
                "duration": dur_str,
                "file": zip_file,
            })
            self.history = self.history[:8]

            def done():
                self.result_text.configure(text=info, text_color=TEXT_PRIMARY)
                self.generate_btn.configure(state="normal", text="Сгенерировать трек")
                self.play_btn.configure(state="normal")
                self.open_btn.configure(state="normal")
                self.counter_label.configure(text=f"{self.track_count} треков")
                self.set_status("Готово")
                self.status_label.configure(text_color=SUCCESS)
                self.set_progress(100)
                self._update_history()
                self._draw_waveform(audio)

            self.after(0, done)
        except Exception as e:
            def err():
                self.generate_btn.configure(state="normal", text="Сгенерировать трек")
                self.set_status(f"Ошибка: {e}")
                self.status_label.configure(text_color=DANGER)
                print(traceback.format_exc())
            self.after(0, err)

    def _update_history(self):
        for w in self.history_scroll.winfo_children():
            w.destroy()

        if not self.history:
            self.history_empty.pack(expand=True, pady=40)
            return

        for entry in self.history:
            item = ctk.CTkFrame(
                self.history_scroll, fg_color=BG_CARD_HOVER,
                corner_radius=14, border_color=BORDER, border_width=1
            )
            item.pack(fill="x", pady=(0, 8))

            ctk.CTkLabel(
                item, text=entry["time"],
                font=("Segoe UI", 10, "bold"), text_color=ACCENT
            ).pack(anchor="w", padx=12, pady=(10, 2))

            ctk.CTkLabel(
                item, text=entry["prompt"],
                font=("Segoe UI", 11), text_color=TEXT_PRIMARY,
                wraplength=240, justify="left"
            ).pack(anchor="w", padx=12, pady=(0, 2))

            ctk.CTkLabel(
                item, text=entry["duration"],
                font=("Segoe UI", 10), text_color=TEXT_DIM
            ).pack(anchor="w", padx=12, pady=(0, 10))

    def _draw_waveform(self, audio):
        for w in self.wave_card.winfo_children():
            w.destroy()

        fig, ax = plt.subplots(figsize=(6.4, 1.2), dpi=80)
        fig.patch.set_facecolor(BG_CARD)
        ax.set_facecolor(BG_CARD)

        self._wave_fig = fig
        self._wave_ax = ax

        canvas = FigureCanvasTkAgg(fig, master=self.wave_card)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=14, pady=14)
        self._wave_canvas = canvas

        self._animate_wave(audio)

    def _toggle_play(self):
        if self.current_audio is None:
            return
        if self.is_playing:
            sd.stop()
            self.is_playing = False
            self.play_btn.configure(text="Play")
        else:
            sd.play(self.current_audio, SAMPLE_RATE)
            self.is_playing = True
            self.play_btn.configure(text="Стоп")

    def _open_folder(self):
        os.startfile(script_dir)


if __name__ == "__main__":
    app = App()
    app.mainloop()
