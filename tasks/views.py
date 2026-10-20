import os
import re
import json
from django.shortcuts import render
from django.http import JsonResponse
from .models import BrainDump, Task
from django.views.decorators.csrf import csrf_exempt
from groq import Groq
from deep_translator import GoogleTranslator


def get_active_groq_model(client):
    models_list = client.models.list().data
    valid_models = [
        m.id for m in models_list
        if all(excl not in m.id.lower() for excl in ['whisper', 'guard', 'tts', 'playai', 'vision', 'embed'])
    ]
    selected_model = valid_models[0]
    for preferred in ['llama-3.3-70b-versatile', 'llama-3.1-70b-versatile', 'gemma2-9b-it']:
        if preferred in valid_models:
            selected_model = preferred
            break
    return selected_model


def parse_llm_json(raw_content):
    if not raw_content:
        return {}
    cleaned = raw_content.strip()
    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def translate_text(text, target_lang):
    if not text or not isinstance(text, str) or target_lang == 'en':
        return str(text or "")
    try:
        res = GoogleTranslator(source='auto', target=target_lang).translate(text)
        return str(res) if res else str(text)
    except Exception:
        return str(text)


def safe_int(val, default=15):
    try:
        return int(val)
    except Exception:
        return default


def index(request):
    return render(request, 'tasks/index.html')


@csrf_exempt
def upload_audio(request):
    if request.method == 'POST':
        audio_file = request.FILES.get('audio')
        typed_text = request.POST.get('text_input', '').strip()
        target_lang = request.POST.get('language', 'en')
        energy_level = request.POST.get('energy', 'medium')

        client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
        raw_transcription = ""

        if audio_file:
            dump = BrainDump.objects.create(
                audio_file=audio_file,
                target_language=target_lang,
                energy_level=energy_level
            )
            with open(dump.audio_file.path, "rb") as file:
                transcription = client.audio.transcriptions.create(
                    file=(dump.audio_file.name, file.read()),
                    model="whisper-large-v3",
                )
            raw_transcription = transcription.text
        elif typed_text:
            dump = BrainDump.objects.create(
                raw_text=typed_text,
                target_language=target_lang,
                energy_level=energy_level
            )
            raw_transcription = typed_text
        else:
            return JsonResponse({'status': 'failed', 'error': 'No input provided'})

        if not raw_transcription or not raw_transcription.strip():
            raw_transcription = "Organize my workspace and complete my main priority task."

        english_text = translate_text(raw_transcription, 'en') if target_lang != 'en' else raw_transcription
        dump.raw_text = english_text or raw_transcription
        dump.save()

        energy_instruction = {
            'low': "The user is in ZOMBIE MODE (extremely low executive function). Make steps absurdly tiny, physical, and effortless (2 minutes per step max). Start with a zero-effort body movement.",
            'medium': "The user has STEADY energy. Break the mission into clear, logical, bite-sized steps of 5 minutes each.",
            'high': "The user is in HYPERFOCUS mode. Group actions into high-momentum power sprints."
        }.get(energy_level, "Break into clear micro-steps.")

        prompt = (
                "You are an ADHD Executive Function Prosthetic. Analyze this brain dump. "
                f"{energy_instruction} "
                "1. Extract a non-empty string for 'core_mission'. "
                "2. Assign a 'friction_rating' (High/Medium/Low). "
                "3. Estimate 'estimated_minutes' (int) for the whole mission. "
                "4. Create 'micro_steps': list of objects with keys 'step' (clear action), 'step_minutes' (int, 1 to 10), 'first_tiny_action' (a 5-second starter trigger), and 'hype' (specific dopamine reward message). "
                "5. Extract all unrelated thoughts, reminders, or distractions into 'side_quests' (list of strings). "
                "Return ONLY a JSON object with keys: 'core_mission', 'friction_rating', 'estimated_minutes', 'micro_steps', 'side_quests'. "
                "Transcript: " + dump.raw_text
        )

        selected_model = get_active_groq_model(client)
        try:
            completion = client.chat.completions.create(
                model=selected_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
        except Exception:
            completion = client.chat.completions.create(
                model=selected_model,
                messages=[{"role": "user", "content": prompt}]
            )

        response_data = parse_llm_json(completion.choices[0].message.content)

        core_mission = str(response_data.get("core_mission") or "Focus Mission")
        friction_rating = str(response_data.get("friction_rating") or "Medium")
        estimated_minutes = safe_int(response_data.get("estimated_minutes"), 15)

        raw_side_quests = response_data.get("side_quests")
        if not isinstance(raw_side_quests, list):
            raw_side_quests = []
        side_quests = [str(sq) for sq in raw_side_quests if sq]

        if target_lang != 'en':
            core_mission = translate_text(core_mission, target_lang) or "Focus Mission"
            side_quests = [translate_text(sq, target_lang) for sq in side_quests]

        raw_steps = response_data.get("micro_steps")
        if not isinstance(raw_steps, list) or len(raw_steps) == 0:
            raw_steps = [
                {
                    "step": f"Begin working on: {core_mission}",
                    "step_minutes": 5,
                    "first_tiny_action": "Take a deep breath and open your workspace",
                    "hype": "First step complete! You broke through the friction."
                }
            ]

        micro_steps = []
        for item in raw_steps:
            if isinstance(item, dict):
                step_text = str(item.get("step") or "Complete next micro-action")
                step_mins = safe_int(item.get("step_minutes"), 5)
                tiny_act = str(item.get("first_tiny_action") or "Focus on the screen for 5 seconds")
                hype_msg = str(item.get("hype") or "Momentum unlocked! Keep going.")
            else:
                step_text = str(item)
                step_mins = 5
                tiny_act = "Focus on the screen for 5 seconds"
                hype_msg = "Momentum unlocked! Keep going."

            if target_lang != 'en':
                step_text = translate_text(step_text, target_lang)
                tiny_act = translate_text(tiny_act, target_lang)
                hype_msg = translate_text(hype_msg, target_lang)

            micro_steps.append({
                "step": step_text,
                "step_minutes": step_mins,
                "first_tiny_action": tiny_act,
                "hype": hype_msg
            })

        task = Task.objects.create(
            brain_dump=dump,
            core_mission=core_mission,
            friction_rating=friction_rating,
            estimated_minutes=estimated_minutes,
            micro_steps=micro_steps,
            side_quests=side_quests
        )

        return JsonResponse({
            'status': 'success',
            'transcript': raw_transcription,
            'task': {
                'id': task.id,
                'core_mission': task.core_mission,
                'friction_rating': task.friction_rating,
                'estimated_minutes': task.estimated_minutes,
                'micro_steps': task.micro_steps,
                'side_quests': task.side_quests
            }
        })
    return JsonResponse({'status': 'failed'})


@csrf_exempt
def unstick_step(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        stuck_step = str(data.get('step') or 'Complete current step')
        target_lang = data.get('language', 'en')

        client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
        selected_model = get_active_groq_model(client)

        prompt = (
                "An ADHD user is experiencing task paralysis on this single step: '" + stuck_step + "'. "
                                                                                                    "Break this single step down into 3 ridiculously tiny, physical micro-actions that require zero thought to start. "
                                                                                                    "Return ONLY a JSON object with key 'sub_steps' containing a list of 3 objects. "
                                                                                                    "Each object must have keys: 'step' (string), 'step_minutes' (int, 1 or 2), 'first_tiny_action' (string), and 'hype' (string)."
        )

        try:
            completion = client.chat.completions.create(
                model=selected_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
        except Exception:
            completion = client.chat.completions.create(
                model=selected_model,
                messages=[{"role": "user", "content": prompt}]
            )

        response_data = parse_llm_json(completion.choices[0].message.content)
        raw_sub = response_data.get("sub_steps")
        if not isinstance(raw_sub, list) or len(raw_sub) == 0:
            raw_sub = [
                {"step": "Sit upright and place your hands on the desk", "step_minutes": 1,
                 "first_tiny_action": "Take one breath", "hype": "Physical barrier broken!"},
                {"step": f"Do just the first 30 seconds of: {stuck_step}", "step_minutes": 2,
                 "first_tiny_action": "Click into the window", "hype": "You started! That is the hardest part."},
                {"step": f"Finish the remainder of: {stuck_step}", "step_minutes": 2,
                 "first_tiny_action": "Keep your hands moving", "hype": "Step conquered!"}
            ]

        sub_steps = []
        for s in raw_sub:
            if isinstance(s, dict):
                st = str(s.get('step') or 'Take one small action')
                sm = safe_int(s.get('step_minutes'), 2)
                ft = str(s.get('first_tiny_action') or 'Start now')
                hp = str(s.get('hype') or 'Nice work!')
            else:
                st = str(s)
                sm = 2
                ft = 'Start now'
                hp = 'Nice work!'

            if target_lang != 'en':
                st = translate_text(st, target_lang)
                ft = translate_text(ft, target_lang)
                hp = translate_text(hp, target_lang)

            sub_steps.append({
                'step': st,
                'step_minutes': sm,
                'first_tiny_action': ft,
                'hype': hp
            })

        return JsonResponse({'status': 'success', 'sub_steps': sub_steps})
    return JsonResponse({'status': 'failed'})


@csrf_exempt
def generate_handoff(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        mission = str(data.get('mission') or 'Current Mission')
        completed = data.get('completed') or []
        remaining = data.get('remaining') or []
        side_quests = data.get('side_quests') or []
        target_lang = data.get('language', 'en')

        client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
        selected_model = get_active_groq_model(client)

        prompt = (
            "Write a clear, calm, professional status handoff message for a team member, manager, or study partner. "
            "The user has ADHD and wants a zero-shame, confident update showing what they accomplished and what is queued next. "
            f"Mission: {mission}. "
            f"Completed Steps: {json.dumps(completed)}. "
            f"Remaining Steps: {json.dumps(remaining)}. "
            f"Parked Follow-ups: {json.dumps(side_quests)}. "
            "Return ONLY a JSON object with a single key 'handoff_message' containing the formatted text."
        )

        try:
            completion = client.chat.completions.create(
                model=selected_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
        except Exception:
            completion = client.chat.completions.create(
                model=selected_model,
                messages=[{"role": "user", "content": prompt}]
            )

        response_data = parse_llm_json(completion.choices[0].message.content)
        msg = str(response_data.get(
            "handoff_message") or f"Status Update for {mission}:\nCompleted: {len(completed)} steps.\nNext up: {len(remaining)} steps.")
        if target_lang != 'en':
            msg = translate_text(msg, target_lang)

        return JsonResponse({'status': 'success', 'handoff_message': msg})
    return JsonResponse({'status': 'failed'})


def get_history(request):
    tasks = Task.objects.order_by('-created_at')[:8]
    history_data = []
    for t in tasks:
        history_data.append({
            'id': t.id,
            'core_mission': t.core_mission,
            'friction_rating': t.friction_rating,
            'estimated_minutes': t.estimated_minutes,
            'micro_steps': t.micro_steps,
            'side_quests': t.side_quests,
            'created_at': t.created_at.strftime("%H:%M")
        })
    return JsonResponse({'status': 'success', 'history': history_data})