import os, io, json, re, requests, logging, math, time
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

import streamlit as st
from supabase import create_client, Client
from components.onboarding import render_onboarding

# --- Config logger ---
logger = logging.getLogger("caloria")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

# --- Assets ---
ASSETS_DIR = Path(__file__).parent / "assets"
LOGO_PATH = ASSETS_DIR / "logo.png"

# --- Secrets check ---
def assert_required_secrets():
    required = ["SUPABASE_URL", "SUPABASE_ANON_KEY"]
    missing = [k for k in required if not st.secrets.get(k)]
    if missing:
        st.error("Configuração do servidor ausente. Contate o suporte.")
        logger.error("Secrets ausentes: %s", ", ".join(missing))
        st.stop()
    else:
        logger.info("Secrets verificados com sucesso.")

# --- Supabase client (singleton) ---
@st.cache_resource
def get_supabase_client() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_ANON_KEY"]
    return create_client(url, key)

supabase = get_supabase_client()

import time

def splash_once():
    """
    Exibe a tela de splash com logo e título customizado.
    Mostra apenas 1x por sessão.
    """
    if st.session_state.get("_splash_done"):
        return

    ph = st.empty()
    with ph.container():
        st.markdown(
            f"""
            <style>
            .caloria-splash {{
              position: fixed; inset: 0; z-index: 9999;
              background: #FFFFFF; /* fundo branco */
              display: flex; flex-direction: column;
              align-items: center; justify-content: center;
            }}
            .caloria-splash-title {{
              margin-top: 12px;
              font-size: 1.2rem;
              font-weight: 700;
              color: #2BAEAE; /* Azul esverdiado */
            }}
            .caloria-splash-sub {{
              margin-top: 6px;
              font-size: 0.9rem;
              color: #FF7A3D; /* Laranja destaque */
              opacity: 0.85;
            }}
            </style>
            <div class="caloria-splash">
              <div id="caloria-splash"></div>
              <div class="caloria-splash-title">CalorIA</div>
              <div class="caloria-splash-sub">Nutrição inteligente com IA</div>
            </div>
            """,
            unsafe_allow_html=True
        )

        try:
            st.image(str(LOGO_PATH), width=160)
        except:
            st.write("Logo não encontrada")

    time.sleep(1.2)  # duração do splash
    ph.empty()
    st.session_state["_splash_done"] = True

def apply_theme():
    st.markdown("""
    <style>
      /* Sidebar teal (sem forçar cor de TODO o texto) */
      [data-testid="stSidebar"] {
        background-color: #2BAEAE !important;
      }
                
      /* Apenas os títulos com classe .sb-title ficam brancos */
      [data-testid="stSidebar"] .sb-title {
        color: #FFFFFF !important;
        font-weight: 700 !important;
        font-size: 1.1rem;
      }

      /* Títulos (mantém padrão do tema pro resto) */
      h1, h2, h3,
      [data-testid="stMarkdownContainer"] h1,
      [data-testid="stMarkdownContainer"] h2,
      [data-testid="stMarkdownContainer"] h3 {
        color: #2BAEAE !important;
        font-weight: 700 !important;
      }

      /* Botões (o tema já cuida do laranja; aqui só refinamos) */
      .stButton > button {
        border-radius: 8px !important;
        font-weight: 600 !important;
      }
      .stButton > button:disabled {
        background-color: #E0E0E0 !important;
        color: #6C757D !important;
        cursor: not-allowed !important;
      }

      /* Selects (fallback se o tema não pegar em algum lugar específico) */
      div[data-baseweb="select"] > div {
        background-color: #FFFFFF !important;
        color: #212529 !important;
        border: 1px solid #ced4da !important;
        border-radius: 6px !important;
      }

      /* Toggle (fallback extra) */
      div[role="switch"] { background-color: #E0E0E0 !important; }
      div[role="switch"][aria-checked="true"] { background-color: #FF7A3D !important; }

      /* Avisos/caixas (ex.: st.info/success) → texto sempre legível */
      div[role="alert"] * { color: #212529 !important; }

      /* Esconder barra preta do topo (dev) */
      header { display: none; }
      [data-testid="stStatusWidget"] { display: none; }
    </style>
    """, unsafe_allow_html=True)

# ======================================================
# STORAGE HELPERS
# ======================================================
def storage_public_url(bucket: str, path: str | None) -> str | None:
    """Retorna URL pública (ou None)."""
    if not path:
        return None
    try:
        res = supabase.storage.from_(bucket).get_public_url(path)
        if isinstance(res, dict):
            data = res.get("data") or {}
            for k in ("publicUrl", "public_url", "publicURL"):
                if data.get(k):
                    return data[k]
        if isinstance(res, str):
            return res
    except Exception:
        pass
    return None

def signed_url(bucket: str, path: str, expires_sec: int = 3600) -> str | None:
    """Para buckets privados: gera URL temporária."""
    try:
        res = supabase.storage.from_(bucket).create_signed_url(path, expires_sec)
        if isinstance(res, dict):
            data = res.get("data") or {}
            return data.get("signedUrl") or data.get("signedURL") or data.get("signed_url")
        if isinstance(res, str):
            return res
    except Exception:
        pass
    return None

def storage_try_extensions(bucket: str, basename: str, exts=(".jpeg", ".jpg", ".png")) -> str | None:
    """Testa basename + extensão e retorna a 1ª URL pública encontrada."""
    for ext in exts:
        url = storage_public_url(bucket, f"{basename}{ext}")
        if url:
            return url
    return None

def storage_try_extensions_safe(bucket: str, basename: str, exts=(".jpg", ".jpeg", ".png")) -> str | None:
    """Versão segura com listagem do bucket (suporta subpastas)."""
    folder, name = os.path.split(basename)
    name = name or basename
    try:
        items = supabase.storage.from_(bucket).list(folder or "")
        names = {it.get("name") for it in items or []}
        for ext in exts:
            candidate = f"{name}{ext}"
            if candidate in names:
                path = f"{folder + '/' if folder else ''}{candidate}"
                return storage_public_url(bucket, path)
    except Exception:
        pass
    return None

def local_img_path(basename: str, exts=(".jpg", ".jpeg", ".png")) -> str | None:
    """Fallback local (apenas funciona no ambiente local)."""
    for ext in exts:
        p = ASSETS_DIR / f"{basename}{ext}"
        if p.exists():
            return str(p)
    return None

def _show_image(url: str | None, caption: str | None = None):
    """Wrapper para st.image com proteção e log."""
    if isinstance(url, str) and url:
        try:
            st.image(url, caption=caption, use_container_width=True)
            return
        except Exception:
            st.warning(f"Falha ao renderizar imagem (valor={repr(url)[:120]}).")
    else:
        st.info("DEBUG: URL inválida → " + repr(url))

from datetime import date, timedelta

def _has_valid_session_for(uid: str) -> bool:
    try:
        sess = supabase.auth.get_session()
        if not sess or not getattr(sess, "user", None):
            return False
        return str(sess.user.id) == str(uid)
    except Exception:
        return False

def get_or_create_subscription(uid: str):
    """Busca assinatura do usuário; se não houver, cria FREE.
       Só toca no DB se houver sessão válida para esse uid."""
    if not uid:
        plan_id, plan_name, inicio, fim = "FREE", "Gratuito", None, None
        st.session_state["plan_id"] = plan_id
        st.session_state["plan_name"] = plan_name
        st.session_state["plan_inicio"] = inicio
        st.session_state["plan_fim"] = fim
        return plan_id, plan_name, inicio, fim

    # se não há sessão válida para este uid, não tenta DB (evita aviso)
    if not _has_valid_session_for(uid):
        plan_id, plan_name, inicio, fim = "FREE", "Gratuito", None, None
        st.session_state["plan_id"] = plan_id
        st.session_state["plan_name"] = plan_name
        st.session_state["plan_inicio"] = inicio
        st.session_state["plan_fim"] = fim
        return plan_id, plan_name, inicio, fim

    plan_labels = {"FREE": "Gratuito", "PRO": "Premium", "PRO_M": "Premium (Mensal)", "PRO_A": "Premium (Anual)"}

    try:
        resp = supabase.table("subscriptions") \
            .select("plan_id,inicio,fim") \
            .eq("user_id", uid) \
            .order("inicio", desc=True) \
            .limit(1) \
            .execute()
        data = getattr(resp, "data", resp)
        if not data:
            hoje = date.today()
            fim_padrao = hoje + timedelta(days=3650)
            # tenta criar FREE padrão
            supabase.table("subscriptions").insert({
                "user_id": uid,
                "plan_id": "FREE",
                "inicio": str(hoje),
                "fim": str(fim_padrao),
                "status": "active",
            }).execute()
            plan_id, inicio, fim = "FREE", str(hoje), str(fim_padrao)
        else:
            sub = data[0]
            plan_id = sub.get("plan_id", "FREE")
            inicio  = sub.get("inicio")
            fim     = sub.get("fim")
    except Exception:
        # Em caso de rede/RLS eventual, fica FREE silencioso
        plan_id, inicio, fim = "FREE", None, None

    plan_name = plan_labels.get(plan_id, "Gratuito")
    st.session_state["plan_id"] = plan_id
    st.session_state["plan_name"] = plan_name
    st.session_state["plan_inicio"] = inicio
    st.session_state["plan_fim"] = fim
    return plan_id, plan_name, inicio, fim

# ======================================================
# GAMIFICAÇÃO / PONTOS
# ======================================================
POINT_VALUES = {
    "login_daily": 1,
    "add_meal": 2,
    "add_measure_photo": 3,
    "birthday": 10,
    "store_review": 20,
    "referral_closed": 50,
    "followup": 5,
}

def _ensure_points_row(user_id: str):
    supabase.table("user_points").upsert({"user_id": user_id}).execute()

def get_points(user_id: str) -> dict:
    _ensure_points_row(user_id)
    resp = supabase.table("user_points").select("*").eq("user_id", user_id).single().execute()
    return resp.data or {"user_id": user_id, "points": 0, "badges": []}

def _record_event(user_id: str, event_type: str, event_key: str, points: int) -> bool:
    try:
        supabase.table("user_points_events").insert({
            "user_id": user_id,
            "event_type": event_type,
            "event_key": event_key,
            "points": points,
        }).execute()
        return True
    except Exception:
        return False

def add_points(user_id: str, event_type: str, event_key: str | None = None, value_override: int | None = None) -> bool:
    if event_key is None:
        if event_type.endswith("_daily"):
            event_key = date.today().isoformat()
        else:
            event_key = datetime.utcnow().isoformat()

    pts = value_override if value_override is not None else POINT_VALUES.get(event_type, 0)
    if pts <= 0:
        return False

    inserted = _record_event(user_id, event_type, event_key, pts)
    if not inserted:
        return False

    _ensure_points_row(user_id)
    current = get_points(user_id)
    new_points = (current.get("points") or 0) + pts
    supabase.table("user_points").update({
        "points": new_points,
        "updated_at": datetime.utcnow().isoformat()
    }).eq("user_id", user_id).execute()
    return True

def award_badge(user_id: str, badge_name: str, meta: dict | None = None) -> None:
    row = get_points(user_id)
    badges = row.get("badges") or []
    names = {b.get("name") for b in badges if isinstance(b, dict)}
    if badge_name in names:
        return
    badges.append({
        "name": badge_name,
        "date": datetime.utcnow().isoformat(),
        "meta": meta or {}
    })
    supabase.table("user_points").update({"badges": badges, "updated_at": datetime.utcnow().isoformat()}) \
        .eq("user_id", user_id).execute()

# ======================================================
# RDA / NUTRIÇÃO
# ======================================================
def get_rda_value(nutrient: str, sex: str, age: int):
    res = (
        supabase.table("rda_nutrients")
        .select("rda_value, unit")
        .eq("nutrient", nutrient)
        .eq("sex", sex)
        .lte("age_min", age)
        .gte("age_max", age)
        .execute()
    )
    if res.data:
        return res.data[0]["rda_value"], res.data[0]["unit"]

    res2 = (
        supabase.table("rda_nutrients")
        .select("rda_value, unit")
        .eq("nutrient", nutrient)
        .eq("sex", "ALL")
        .lte("age_min", age)
        .gte("age_max", age)
        .execute()
    )
    if res2.data:
        return res2.data[0]["rda_value"], res2.data[0]["unit"]

    return None, None

def _fator_atividade(txt: str) -> float:
    return {
        "Sedentário (pouco ou nenhum exercício)": 1.2,
        "Leve (1–3x/semana)": 1.375,
        "Moderado (3–5x/semana)": 1.55,
        "Alto (6–7x/semana)": 1.725,
        "Atleta/Extremo (2x/dia)": 1.9,
    }.get(txt, 1.2)

def _bmr_mifflin(kg: float, cm: float, anos: int, sex: str) -> float:
    s = 5 if sex == "Masculino" else -161
    return (10*kg) + (6.25*cm) - (5*anos) + s

def _tdee(kg, cm, anos, sex, atividade_txt):
    return _bmr_mifflin(kg, cm, anos, sex) * _fator_atividade(atividade_txt)

def _idade_from_dob(dob: date) -> int:
    if not dob:
        return 30
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

def _semanas_para_alvo(peso_atual, peso_meta, objetivo):
    if objetivo == "Emagrecer":
        perda_por_sem = 0.5
        delta = max(peso_atual - peso_meta, 0.0)
        return 0 if delta <= 0 else math.ceil(delta / perda_por_sem)
    elif objetivo == "Ganhar massa":
        ganho_por_sem = 0.25
        delta = max(peso_meta - peso_atual, 0.0)
        return 0 if delta <= 0 else math.ceil(delta / ganho_por_sem)
    return 0

# ======================================================
# IA DETECT FOODS
# ======================================================
def ai_detect_foods_from_image_openrouter(image_url: str) -> List[Dict[str, Any]]:
    api_key = st.secrets.get("OPENROUTER_API_KEY")
    model = st.secrets.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    if not api_key:
        return []

    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://seu-dominio-ou-localhost",
        "X-Title": "CalorIA - Foto Refeição",
        "Content-Type": "application/json",
    }

    system_prompt = (
        "Você é um assistente de nutrição. Dada uma foto de refeição, retorne JSON com "
        "lista de itens no formato: {\"items\":[{\"food\":\"nome\",\"grams\":int,\"confidence\":0-1}]}."
    )
    user_text = (
        "Identifique os principais alimentos visíveis, estime gramas (inteiro) e confiança. "
        "Responda APENAS em JSON válido com a chave 'items'."
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": image_url}}
            ]}
        ],
        "temperature": 0.2,
    }

    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers, json=payload, timeout=45
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        try:
            parsed = json.loads(content)
        except Exception:
            match = re.search(r"\{.*\}", content, flags=re.S)
            parsed = json.loads(match.group(0)) if match else {}

        items = parsed.get("items") or []
        out = []
        for it in items:
            food = str(it.get("food") or "").strip()
            grams = float(it.get("grams") or 0)
            conf  = float(it.get("confidence") or 0)
            if food:
                out.append({"food": food, "grams": max(0.0, grams), "confidence": max(0.0, min(conf, 1.0))})
        return out
    except Exception:
        return []

# ======================================================
# DB HELPERS
# ======================================================

def salvar_medidas(
    user_id: str,
    ref_date: date,
    chest_cm: float | None = None,
    arm_cm: float | None = None,
    waist_cm: float | None = None,
    abdomen_cm: float | None = None,
    hip_cm: float | None = None,
    thigh_cm: float | None = None,
    calf_cm: float | None = None,
):
    """
    Salva as medidas do usuário na tabela 'measurements'.
    Retorna o ID gerado (UUID) se sucesso, ou None se falhar.
    """
    try:
        payload = {
            "user_id": user_id,
            "ref_date": str(ref_date),
            "chest_cm": chest_cm,
            "arm_cm": arm_cm,
            "waist_cm": waist_cm,
            "abdomen_cm": abdomen_cm,
            "hip_cm": hip_cm,
            "thigh_cm": thigh_cm,
            "calf_cm": calf_cm,
        }
        res = supabase.table("measurements").insert(payload).execute()
        if res.data and isinstance(res.data, list):
            return res.data[0].get("id")
        return None
    except Exception as e:
        st.warning(f"Erro ao salvar medidas: {e}")
        return None

# ======================================================
# DB HELPERS - Refeições
# ======================================================
def salvar_refeicao_no_supabase(
    user_id: str,
    ref_date: str,
    meal_type: str,
    description: str,
    qty_g: float,
    kcal: float,
    protein_g: float,
    carbs_g: float,
    fat_g: float,
    photo_path: str | None = None,
):
    """Insere uma refeição no diário alimentar e retorna o id."""
    try:
        res = supabase.table("food_diary").insert({
            "user_id": user_id,
            "ref_date": ref_date,
            "meal_type": meal_type,
            "description": description,
            "qty_g": qty_g,
            "kcal": kcal,
            "protein_g": protein_g,
            "carbs_g": carbs_g,
            "fat_g": fat_g,
            "photo_path": photo_path,
        }).execute()
        if res.data:
            return res.data[0].get("id")
    except Exception as e:
        st.error(f"Erro ao salvar refeição: {e}")
    return None

# ======================================================
# DB HELPERS
# ======================================================
# --- Helpers Perfil / User Nutrition ---
def db_get_profile(user_id: str):
    try:
        res = supabase.table("profiles").select("*").eq("id", user_id).single().execute()
        return res.data
    except Exception:
        return None

def db_upsert_profile(user_id: str, email: str, nome: str | None = None):
    payload = {"id": user_id, "email": email}
    if nome is not None:
        payload["nome"] = nome
    try:
        res = supabase.table("profiles").upsert(
            payload,
            on_conflict="id",
            returning="representation"
        ).execute()
        if isinstance(res.data, list) and res.data:
            return res.data[0]
        return res.data
    except Exception as e:
        st.warning(f"Não foi possível salvar perfil: {e}")
        return None

def db_get_user_nutrition(user_id: str):
    try:
        res = supabase.table("user_nutrition").select("*").eq("user_id", user_id).single().execute()
        return res.data
    except Exception:
        return None  # tabela pode não existir ainda

def db_upsert_user_nutrition(user_id: str, altura_cm: float | None, peso_kg: float | None):
    try:
        payload = {"user_id": user_id}
        if altura_cm is not None:
            payload["height_cm"] = altura_cm
        if peso_kg is not None:
            payload["weight_kg"] = peso_kg
        res = supabase.table("user_nutrition").upsert(
            payload,
            on_conflict="user_id",
            returning="representation"
        ).execute()
        if isinstance(res.data, list) and res.data:
            return res.data[0]
        return res.data
    except Exception:
        st.info("Tabela 'user_nutrition' não encontrada (ok para MVP).")
        return None

def db_list_recipes(search: str = "", categorias: Optional[list] = None) -> List[Dict[str, Any]]:
    q = supabase.table("recipes").select("*")
    if search:
        q = q.ilike("titulo", f"%{search}%")
    if categorias:
        q = q.in_("categoria", categorias)
    res = q.order("created_at", desc=True).execute()
    return res.data or []

def recipe_image_public_url(path: Optional[str]) -> Optional[str]:
    """Monta URL pública de uma imagem de receita no bucket 'recipes'."""
    if not path:
        return None
    return storage_public_url("recipes", path)

# --- Macros (user_macros) ---
def save_user_macros(uid: str, resumo: dict):
    """Salva cálculo de macros no Supabase."""
    data = {
        "user_id": uid,
        "peso": resumo["peso"],
        "altura": resumo["altura"],
        "idade": resumo["idade"],
        "sexo": resumo["sexo"],
        "atividade": resumo["atividade"],
        "objetivo": resumo["objetivo"],
        "bmr": resumo["bmr"],
        "tdee": resumo["tdee"],
        "kcal_alvo": resumo["kcal_alvo"],
        "protein_g": resumo["g_prot"],
        "carbs_g": resumo["g_carb"],
        "fats_g": resumo["g_gord"],
        "agua_l": resumo["agua_l"],
    }
    supabase.table("user_macros").insert(data).execute()

# --- Cardápios (meal_plans) ---
def get_meal_plan_for_target(kcal_alvo: int):
    """Busca cardápio mais próximo do alvo calórico."""
    res = supabase.table("meal_plans") \
        .select("*") \
        .order(f"abs(kcal_alvo - {kcal_alvo})") \
        .limit(1) \
        .execute()
    if res.data:
        return res.data[0]
    return None

def is_user_coaching(uid: str) -> bool:
    """Retorna True se o usuário for de coaching (plano especial)."""
    try:
        # Aqui assumimos que na tabela profiles existe um campo "coaching"
        resp = (
            supabase.table("profiles")
            .select("coaching")
            .eq("id", uid)
            .single()
            .execute()
        )
        data = resp.data or {}
        return bool(data.get("coaching"))
    except Exception:
        return False


# ======================================================
# NAVIGATION HELPERS
# ======================================================
def set_nav(dest: str):
    """Atalho para trocar a aba/nav atual e rerun."""
    st.session_state["nav"] = dest
    st.rerun()
