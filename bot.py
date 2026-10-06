import os, asyncio, logging, subprocess, tempfile, json, re
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
VOICE = os.getenv("OPENAI_VOICE", "alloy")

if not BOT_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError("BOT_TOKEN dan OPENAI_API_KEY harus diisi di Railway Variables")

client = OpenAI(api_key=OPENAI_API_KEY)
logging.basicConfig(level=logging.INFO)

SYSTEM_PROMPT = """
Kamu adalah penulis naskah video pendek Indonesia untuk Telegram AI Video Bot.
Buat video vertikal 9:16 yang cepat, menarik, dan mudah dipahami.
Gunakan 6-8 scene untuk video sekitar 45-60 detik.
Output HARUS JSON valid:
{"title":"...","narration":"...","scenes":[{"text":"...","visual_prompt":"..."}]}
Jangan gunakan markdown.
"""

def make_script(topic):
    r = client.chat.completions.create(
        model=MODEL, temperature=0.8,
        response_format={"type":"json_object"},
        messages=[
            {"role":"system","content":SYSTEM_PROMPT},
            {"role":"user","content":f"Buat video tentang: {topic}"}
        ])
    return json.loads(r.choices[0].message.content)

def make_voice(text, out):
    with client.audio.speech.with_streaming_response.create(
        model="gpt-4o-mini-tts", voice=VOICE, input=text,
        instructions="Baca bahasa Indonesia dengan natural, jelas, dan energik seperti narator video pendek."
    ) as response:
        response.stream_to_file(out)

def make_srt(text, out):
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]
    if not parts: parts=[text]
    def ts(x):
        h=int(x//3600); x-=h*3600; m=int(x//60); x-=m*60
        s=int(x); ms=int(round((x-s)*1000))
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    lines=[]
    for i,p in enumerate(parts,1):
        a=(i-1)*4; b=i*4
        lines += [str(i),f"{ts(a)} --> {ts(b)}",p,""]
    out.write_text("\n".join(lines), encoding="utf-8")

def render(audio, srt, out):
    sp=str(srt).replace("\\","/").replace(":","\\:")
    vf=(f"subtitles='{sp}':force_style="
        "'FontName=DejaVu Sans,FontSize=20,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Alignment=2,MarginV=100'")
    cmd=["ffmpeg","-y","-f","lavfi","-i","color=c=0x171717:s=1080x1920:r=30",
         "-i",str(audio),"-vf",vf,"-c:v","libx264","-preset","veryfast",
         "-crf","28","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k",
         "-shortest","-movflags","+faststart",str(out)]
    subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 AI VIDEO BOT V1.1 siap!\n\n"
        "Kirim ide video, contoh:\n5 fakta unik tentang luar angkasa\n\n"
        "Bot membuat script, voice-over, subtitle, dan MP4 9:16."
    )

async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic=(update.message.text or "").strip()
    if len(topic)<5:
        await update.message.reply_text("Kirim ide video yang lebih lengkap.")
        return
    status=await update.message.reply_text("🧠 Membuat script AI...")
    with tempfile.TemporaryDirectory() as td:
        d=Path(td)
        try:
            script=await asyncio.to_thread(make_script,topic)
            await status.edit_text("🎙️ Membuat voice-over AI...")
            audio=d/"voice.mp3"
            await asyncio.to_thread(make_voice,script["narration"],audio)
            await status.edit_text("📝 Membuat subtitle...")
            srt=d/"subtitle.srt"
            await asyncio.to_thread(make_srt,script["narration"],srt)
            await status.edit_text("🎬 Rendering video 9:16...")
            video=d/"video.mp4"
            await asyncio.to_thread(render,audio,srt,video)
            await status.edit_text("📤 Mengirim video...")
            with video.open("rb") as f:
                await update.message.reply_video(
                    video=f,
                    caption=f"🎬 {script.get('title','AI Video')}\n\nDibuat oleh AI Video Bot V1.1",
                    supports_streaming=True)
            await status.delete()
        except Exception:
            logging.exception("Generation failed")
            await status.edit_text("❌ Gagal. Cek Railway → Deployments → Logs.")

def main():
    app=Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,generate))
    logging.info("AI Video Bot berjalan...")
    app.run_polling()

if __name__=="__main__":
    main()
