# pages/06_Receitas.py
# -------------------------------------------------------------
# Receitas (via Supabase) com gating por plano (Free x PRO)
# - Lê plano do st.session_state (setado no pós-login)
# - Busca receitas em public.recipes
# - Imagens do bucket 'recipes' no Storage
# -------------------------------------------------------------
import streamlit as st
from typing import List, Dict, Any, Optional

st.set_page_config(
    page_title="Receitas",
    page_icon="🍽️",
    layout="wide",
    initial_sidebar_state="expanded"
)

from helpers import (
    get_or_create_subscription, get_rda_value,
    _show_image, storage_public_url, apply_theme,
    db_list_recipes, recipe_image_public_url
)

apply_theme()

# -------------------------------------------------------------
# Se NÃO estiver logado, volta pra Home
if not st.session_state.get("sb_session"):
    st.switch_page("app_calorias.py")

# -------------------------------------------------------------
st.title("🍽️ Receitas")

# -------- Sessão / Plano --------
uid = st.session_state.get("user_id")
plan_id, plan_name, _, _ = get_or_create_subscription(uid)
is_pro = (plan_id == "PRO")

st.caption(
    f"Plano atual: **{plan_name}** — "
    + ("Acesso completo liberado." if is_pro else "Acesso parcial: 5 receitas grátis desbloqueadas.")
)

# -------- Filtros --------
with st.container(border=True):
    cols = st.columns([2, 1, 1, 1])
    with cols[0]:
        q = st.text_input("Buscar por título", placeholder="Ex.: frango, aveia, salada…")
    with cols[1]:
        all_rows = db_list_recipes()
        cats = sorted({r["categoria"] for r in all_rows}) if all_rows else []
        cat_sel = st.multiselect("Categoria", options=cats, default=[])
    with cols[2]:
        only_quick = st.toggle("Até 15 min", value=False)
    with cols[3]:
        sort_opt = st.selectbox("Ordenar por", ["Relevância", "Menor kcal", "Maior proteína"])

# -------- Consulta --------
rows = db_list_recipes(search=q, categorias=cat_sel if cat_sel else None)

if only_quick:
    rows = [r for r in rows if (r.get("tempo_min") or 0) <= 15]

if sort_opt == "Menor kcal":
    rows = sorted(rows, key=lambda r: r.get("kcal", 0))
elif sort_opt == "Maior proteína":
    rows = sorted(rows, key=lambda r: float(r.get("proteina_g") or 0), reverse=True)

# -------- Gating por plano --------
if is_pro:
    visiveis = rows
    bloqueadas = []
else:
    visiveis = [r for r in rows if r.get("degusta   cao_gratis")]
    bloqueadas = [r for r in rows if not r.get("degustacao_gratis")]

# --- Micronutrientes ---
def show_micros(receita, sex="M", age=30):
    micros = {
        "Vitamina C": (receita.get("vitamina_c_mg"), "mg"),
        "Vitamina D": (receita.get("vitamina_d_ug"), "µg"),
        "Cálcio":     (receita.get("calcio_mg"), "mg"),
        "Ferro":      (receita.get("ferro_mg"), "mg"),
        "Magnésio":   (receita.get("magnesio_mg"), "mg"),
    }
    st.markdown("#### 🧪 Micronutrientes")
    for nut, (val, unit) in micros.items():
        if val:
            rda, unit_ref = get_rda_value(nut, sex, age)
            if rda:
                pct = (val / rda) * 100
                st.write(f"- {nut}: {val}{unit} → {pct:.0f}% da meta ({rda}{unit})")
            else:
                st.write(f"- {nut}: {val}{unit}")

# -------- UI helpers --------
def card_receita(r: Dict[str, Any], locked: bool = False):
    box = st.container(border=True)
    with box:
        cols = st.columns([1, 2])
        with cols[0]:
            url = recipe_image_public_url(r.get("imagem_url"))
            if url:
                _show_image(url)
            else:
                st.empty()
        with cols[1]:
            titulo = ("🔒 " if locked else "") + str(r.get("titulo", ""))
            st.markdown(f"### {titulo}")

            tempo_min = r.get("tempo_min") or 0
            porcoes   = r.get("porcoes") or 1
            st.write(f"**Categoria:** {r.get('categoria','-')}  •  {tempo_min} min  •  {porcoes} porção(ões)")

            kcal = r.get("kcal") or 0
            P = r.get("proteina_g") or 0
            C = r.get("carbo_g") or 0
            G = r.get("gordura_g") or 0

            show_micros(r, sex="M", age=30)  # depois puxa sexo/idade real
            st.write(f"**Kcal:** {kcal}  |  **P:** {P} g  •  **C:** {C} g  •  **G:** {G} g")

            if locked:
                st.info("Receita Premium. Faça o upgrade do seu plano.")
            else:
                with st.expander("Ver ingredientes e preparo"):
                    st.markdown("**Ingredientes**")
                    for ing in (r.get("ingredientes") or []):
                        st.write(f"- {ing}")
                    st.markdown("**Preparo**")
                    for i, step in enumerate((r.get("preparo") or []), start=1):
                        st.write(f"{i}. {step}")

# -------- Render --------
if not rows:
    st.info("Nenhuma receita encontrada com esses filtros.")
else:
    cols = st.columns(2)
    for i, r in enumerate(visiveis):
        with cols[i % 2]:
            card_receita(r, locked=False)

    if bloqueadas:
        st.subheader("🔒 Receitas Premium")
        cols2 = st.columns(2)
        for i, r in enumerate(bloqueadas):
            with cols2[i % 2]:
                card_receita(r, locked=True)

st.divider()
st.caption("Banco real • As imagens vêm do Storage. Use paginação se crescer muito.")
