# pages/05_Perfil_Conta.py
# -------------------------------------------------------------
# Perfil / Conta
# - Mostra plano do st.session_state
# - Edita nome/e-mail em public.profiles
# - Salva altura/peso em public.user_nutrition (se existir)
# -------------------------------------------------------------
import datetime as dt
import streamlit as st
from datetime import date

st.set_page_config(
    page_title="Perfil / Conta",
    page_icon="👤",
    layout="centered",
    initial_sidebar_state="expanded"
)

from helpers import (
    db_get_profile, db_upsert_profile,
    db_get_user_nutrition, db_upsert_user_nutrition,
    add_points, award_badge,
    apply_theme, get_or_create_subscription,
)

apply_theme()

# -------- Sessão --------
uid   = st.session_state.get("user_id")
email = st.session_state.get("user_email", "-")

if not uid:
    st.warning("Faça login para ver seu perfil.")
    st.stop()

# -------- Plano --------
plan_id, plan_name, inicio, fim = get_or_create_subscription(uid)

# -------- Dados atuais --------
prof = db_get_profile(uid) or {"email": email, "nome": ""}
nut  = db_get_user_nutrition(uid) or {}

# Checagem de aniversário
if prof and prof.get("birthday"):
    birthday = date.fromisoformat(prof["birthday"])
    today = date.today()
    if birthday.month == today.month and birthday.day == today.day:
        if add_points(uid, "birthday", event_key=today.isoformat()):
            award_badge(uid, "Parabéns pelo aniversário 🎂")
            st.toast("🎉 Feliz aniversário! +10 FC adicionados 🎂")

# ==========================
# Status do Plano
# ==========================
st.subheader("Status do Plano")
col1, col2 = st.columns(2)
with col1:
    st.metric("Plano", plan_name)
    st.write(f"**E-mail:** {email}")
with col2:
    if inicio and fim:
        d_hoje   = dt.date.today()
        d_inicio = dt.date.fromisoformat(inicio)
        d_fim    = dt.date.fromisoformat(fim)
        total    = (d_fim - d_inicio).days
        passados = max(0, (min(d_hoje, d_fim) - d_inicio).days)
        restantes= max(0, (d_fim - max(d_hoje, d_inicio)).days)
        pct      = passados/total if total>0 else 0
        st.metric("Dias restantes", restantes)
        st.write("Progresso do plano")
        st.progress(min(1.0, max(0.0, pct)))
    else:
        st.info("Sem assinatura ativa (padrão: Gratuito).")

st.divider()

# ==========================
# Dados Pessoais
# ==========================
st.subheader("Dados Pessoais")
with st.form("form_dados_pessoais"):
    nome_in  = st.text_input("Nome",  value=prof.get("nome")  or "")
    email_in = st.text_input("E-mail", value=prof.get("email") or email)
    colA, colB = st.columns(2)
    with colA:
        altura_in = st.number_input(
            "Altura (cm)", min_value=0.0, max_value=300.0,
            value=float(nut.get("height_cm") or 0.0), step=0.5
        )
    with colB:
        peso_in = st.number_input(
            "Peso (kg)", min_value=0.0, max_value=500.0,
            value=float(nut.get("weight_kg") or 0.0), step=0.1
        )
    submitted = st.form_submit_button("💾 Salvar alterações")

if submitted:
    db_upsert_profile(uid, email_in, nome=nome_in)
    db_upsert_user_nutrition(uid, altura_in or None, peso_in or None)
    st.success("Perfil atualizado.")

st.divider()

# ==========================
# Acesso a Conteúdos
# ==========================
st.subheader("Acesso a Conteúdos")
if plan_id == "PRO":
    st.success("🔓 Receitas Premium: **Liberado**")
else:
    st.warning("🔒 Receitas Premium: **Bloqueado** no seu plano atual.")
