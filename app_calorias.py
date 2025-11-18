# app_calorias.py
# Mini app em Streamlit
# - Calcula BMR/TDEE/Água
# - Seleciona objetivo (cut/manutenção/bulk) com ajuste automático de calorias
# - Macros por g/kg ou por %
# - Exporta PDF simples com o plano diário
# - Integra com Supabase (plano, follow up, medidas, diário, jejum)

import io
from datetime import datetime, date
import streamlit as st
import pandas as pd
from pathlib import Path

st.set_page_config(
    page_title="calorIA - Nutrição Inteligente",
    page_icon="🍽️",
    layout="centered",
    initial_sidebar_state="expanded"
)

from helpers import (
    supabase,
    get_points,
    award_badge,
    storage_public_url,
    local_img_path,
    _show_image,
    ai_detect_foods_from_image_openrouter,
    _bmr_mifflin as bmr_mifflin,
    _tdee as tdee,
    add_points,
    salvar_medidas,
    salvar_refeicao_no_supabase,
    set_nav,
    splash_once,
    render_onboarding,
    apply_theme, get_meal_plan_for_target,
    is_user_coaching
)

apply_theme()
splash_once()

# Reportlab (PDF export)
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


# -------------------------------------------------------
# Estado base
if "sb_session" not in st.session_state:
    st.session_state["sb_session"] = None


# -------------------------------------------------------
# Funções auxiliares locais
def agua_diaria_ml(peso_kg: float) -> float:
    return peso_kg * 35.0


def kcal_to_macros_grams(kcal, pct_p, pct_c, pct_f):
    kcal_p = kcal * pct_p / 100.0
    kcal_c = kcal * pct_c / 100.0
    kcal_f = kcal * pct_f / 100.0
    g_p = kcal_p / 4
    g_c = kcal_c / 4
    g_f = kcal_f / 9
    total = pct_p + pct_c + pct_f
    norm = (pct_p / total * 100, pct_c / total * 100, pct_f / total * 100)
    return g_p, g_c, g_f, norm


def grams_from_gkg(peso, p_gkg, f_gkg, kcal_alvo):
    prot_g = p_gkg * peso
    gord_g = f_gkg * peso
    kcal_prot = prot_g * 4
    kcal_gord = gord_g * 9
    kcal_rest = kcal_alvo - (kcal_prot + kcal_gord)
    carb_g = max(0, kcal_rest / 4)
    return prot_g, carb_g, gord_g, kcal_rest


def gerar_pdf_bytes(resumo: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []
    story.append(Paragraph("Plano Diário", styles["Title"]))
    story.append(Spacer(1, 12))
    for k, v in resumo.items():
        story.append(Paragraph(f"{k}: {v}", styles["Normal"]))
    doc.build(story)
    pdf = buf.getvalue()
    buf.close()
    return pdf


# -------------------------------------------------------
# Render principal
def render_app_calorias():
    st.subheader("🍽️ Calorias & Macros")

    session = st.session_state.get("sb_session")
    uid = session.user.id if session else None

    aba_plano, aba_dash, aba_diario = st.tabs(
        ["📊 Plano diário", "📈 Dashboard", "📒 Diário alimentar"]
    )

    # =====================================================
    # ABA PLANO DIÁRIO
    # =====================================================
    with aba_plano:
        with st.form("dados_basicos_plano"):
            st.subheader("1) Dados básicos")
            col1, col2 = st.columns(2)

            with col1:
                peso = st.number_input("Peso (kg)", 30.0, 300.0, 75.0, step=0.1)
                altura = st.number_input("Altura (cm)", 120.0, 230.0, 175.0, step=0.5)
                idade = st.number_input("Idade (anos)", 14, 100, 30, step=1)

            with col2:
                sexo = st.selectbox("Sexo", ["Masculino", "Feminino"])
                atividade = st.selectbox(
                    "Nível de atividade",
                    [
                        "Sedentário (pouco ou nenhum exercício)",
                        "Leve (1–3x/semana)",
                        "Moderado (3–5x/semana)",
                        "Alto (6–7x/semana)",
                        "Atleta/Extremo (2x/dia)",
                    ],
                )
                default_email = st.session_state.get("saved_email", "")
                email = st.text_input("E-mail (opcional, protótipo)")

            st.subheader("2) Objetivo calórico")
            objetivo = st.selectbox(
                "Selecione o objetivo",
                ["Cut (déficit)", "Manutenção", "Bulk (superávit)"],
                index=1,
            )
            ajuste_padrao = {"Cut (déficit)": -20, "Manutenção": 0, "Bulk (superávit)": 15}[objetivo]
            ajuste_percent = st.slider(
                "Ajuste calórico (%)",
                -40, 40, ajuste_padrao,
                step=1,
                help="Percentual aplicado sobre as calorias de manutenção (TDEE).",
            )

            st.subheader("3) Definição de Macros")
            metodo_macros = st.radio("Como definir?", ["Por g/kg", "Por %"], index=0)

            if metodo_macros == "Por g/kg":
                colp, colf = st.columns(2)
                with colp:
                    p_gkg = st.number_input("Proteína (g/kg)", 0.5, 3.0, 2.0, step=0.1)
                with colf:
                    f_gkg = st.number_input("Gordura (g/kg)", 0.2, 2.0, 0.8, step=0.05)
                p_pct = c_pct = f_pct = None
            else:
                colp, colc, colf = st.columns(3)
                with colp:
                    p_pct = st.number_input("Proteína (%)", 0, 100, 30, step=1)
                with colc:
                    c_pct = st.number_input("Carboidratos (%)", 0, 100, 40, step=1)
                with colf:
                    f_pct = st.number_input("Gorduras (%)", 0, 100, 30, step=1)
                p_gkg = f_gkg = None

            calcular = st.form_submit_button("Calcular")

        if calcular:
            avisos = []

            bmr = bmr_mifflin(peso, altura, idade, sexo)
            tdee_val = tdee(peso, altura, idade, sexo, atividade)
            kcal_alvo = tdee_val * (1 + ajuste_percent / 100.0)
            agua = agua_diaria_ml(peso)

            if metodo_macros == "Por %":
                g_p, g_c, g_f, (pN, cN, fN) = kcal_to_macros_grams(kcal_alvo, p_pct, c_pct, f_pct)
                if abs((p_pct + c_pct + f_pct) - 100) > 0.01:
                    st.info(
                        f"As porcentagens somavam {p_pct + c_pct + f_pct:.1f}%. Normalizadas: Prot {pN:.1f}%, Carbo {cN:.1f}%, Gord {fN:.1f}%."
                    )
                prot_g, carb_g, gord_g = g_p, g_c, g_f
            else:
                prot_g, carb_g, gord_g, kcal_rest = grams_from_gkg(peso, p_gkg, f_gkg, kcal_alvo)
                if kcal_rest < 0:
                    avisos.append("As calorias alvo ficaram insuficientes para carboidratos. Ajuste metas.")

            # Salva metas na sessão
            st.session_state["kcal_alvo"] = float(kcal_alvo)
            st.session_state["prot_g"] = float(prot_g)
            st.session_state["carb_g"] = float(carb_g)
            st.session_state["gord_g"] = float(gord_g)

            st.subheader("Resultados")
            m1, m2, m3 = st.columns(3)
            m1.metric("BMR (Mifflin)", f"{bmr:,.0f} kcal/d")
            m2.metric("TDEE", f"{tdee_val:,.0f} kcal/d")
            m3.metric("Água diária", f"{agua/1000:,.2f} L/d")

            st.write(f"**Objetivo:** {objetivo}  |  **Alvo:** **{kcal_alvo:,.0f} kcal/dia**")

            # Macros
            kcal_p = prot_g * 4
            kcal_c = carb_g * 4
            kcal_f = gord_g * 9
            c1, c2, c3 = st.columns(3)
            c1.metric("Proteína", f"{prot_g:,.0f} g", help=f"{kcal_p:,.0f} kcal")
            c2.metric("Carboidratos", f"{carb_g:,.0f} g", help=f"{kcal_c:,.0f} kcal")
            c3.metric("Gorduras", f"{gord_g:,.0f} g", help=f"{kcal_f:,.0f} kcal")

            if avisos:
                for a in avisos:
                    st.warning(a)

            st.divider()
            st.write("**Exportar**")
            if REPORTLAB_AVAILABLE:
                resumo = {
                    "peso": peso,
                    "altura": altura,
                    "idade": idade,
                    "sexo": sexo,
                    "atividade": atividade,
                    "bmr": round(bmr),
                    "tdee": round(tdee_val),
                    "kcal_alvo": round(kcal_alvo),
                    "objetivo": objetivo,
                    "ajuste_percent": ajuste_percent,
                    "g_prot": round(prot_g),
                    "g_carb": round(carb_g),
                    "g_gord": round(gord_g),
                    "kcal_prot": round(kcal_p),
                    "kcal_carb": round(kcal_c),
                    "kcal_gord": round(kcal_f),
                    "agua_l": round(agua / 1000, 2),
                    "avisos": avisos,
                }
                pdf_bytes = gerar_pdf_bytes(resumo)
                nome_pdf = f"Plano_Diario_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
                st.download_button("📄 Baixar PDF", data=pdf_bytes, file_name=nome_pdf, mime="application/pdf")
            else:
                st.info("Para exportar PDF, instale **reportlab** (`pip install reportlab`).")
    
            # --- [BOTÃO: SALVAR NO SUPABASE] ---
            if st.session_state.get("sb_session") is None:
                st.info("Faça login para salvar seu plano.")
            else:
                if st.button("💾 Salvar plano no Supabase", key="btn_salvar_plano"):
                    try:
                        uid = st.session_state["sb_session"].user.id
                        save_user_macros(uid, resumo)   # ✅ novo
                        st.success("Plano salvo com sucesso!")
                    except Exception as e:
                        st.error(f"Erro ao salvar: {e}")

            # === [LISTAR PLANOS SALVOS] ===
            if st.session_state.get("sb_session"):
                try:
                    uid = st.session_state["sb_session"].user.id
                    rows = (
                        supabase.table("user_nutrition")
                        .select("*")
                        .eq("user_id", uid)
                        .order("created_at", desc=True)
                        .limit(10)
                        .execute()
                    )
                    if rows.data:
                        st.write("**Seus últimos planos:**")
                        for r in rows.data:
                            st.write(
                                f"- {r['created_at']}: {r['target_kcal']} kcal | P {r['protein_g']}g • C {r['carbs_g']}g • G {r['fats_g']}g | Água {r['water_l']} L"
                            )
                    else:
                        st.caption("Você ainda não tem planos salvos.")
                except Exception as e:
                    st.warning(f"Não foi possível listar planos: {e}")
        else:
            st.info(
                "Preencha os dados e clique em **Calcular** para ver resultados e liberar a exportação em PDF."
            ) 

            # === [Sugestão de Cardápio] ===
            st.divider()
            st.subheader("Sugestão de Cardápio")

            if "kcal_alvo" in locals():  # só roda se kcal_alvo já foi calculado
                uid = st.session_state.get("user_id")
                plan_id = st.session_state.get("plan_id", "FREE")

                cardapio = get_meal_plan_for_target(round(kcal_alvo))

                if cardapio:
                    if plan_id == "FREE":
                        st.info("Exemplo gratuito de cardápio (upgrade para ver todos).")
                        st.write(f"**{cardapio['titulo']}** — {cardapio['kcal_alvo']} kcal")
                        st.json(cardapio["refeicoes"])  # exemplo simples
                    else:  # PRO
                        st.success("Seu cardápio premium baseado no cálculo:")
                        st.write(f"**{cardapio['titulo']}** — {cardapio['kcal_alvo']} kcal")
                        for refeicao in cardapio["refeicoes"]:
                            st.markdown(f"**{refeicao['nome']}**")
                            for item in refeicao["itens"]:
                                st.write(f"- {item}")
                else:
                    st.warning("Nenhum cardápio correspondente cadastrado ainda.")
            else:
                st.caption("⚠️ Calcule seus macros primeiro para ver um cardápio sugerido.")


    with aba_diario:
        st.subheader("⏳ Jejum intermitente")

        session = st.session_state.get("sb_session")
        if session:
            uid = session.user.id

            fasting_on = st.checkbox("Ativar jejum intermitente")

            if fasting_on:
                colj1, colj2 = st.columns(2)
                with colj1:
                    start_time = st.time_input("Início do jejum")
                with colj2:
                    end_time = st.time_input("Fim do jejum (opcional)", value=None)

                if st.button("Salvar jejum", key="btn_salvar_jejum"):
                    import datetime as dt

                    today = dt.date.today()
                    start_dt = dt.datetime.combine(today, start_time)
                    end_dt = dt.datetime.combine(today, end_time) if end_time else None
                    try:
                        supabase.table("fasting_log").insert(
                            {
                                "user_id": uid,
                                "start_time": start_dt.isoformat(),
                                "end_time": end_dt.isoformat() if end_dt else None,
                            }
                        ).execute()
                        st.success("Jejum salvo!")
                    except Exception as e:
                        st.error(f"Erro ao salvar jejum: {e}")

                st.markdown("### Histórico de jejuns")
                try:
                    resp = (
                        supabase.table("fasting_log")
                        .select("*")
                        .eq("user_id", uid)
                        .order("start_time", desc=True)
                        .limit(10)
                        .execute()
                    )
                    rows = resp.data or []
                    if rows:
                        import pandas as pd

                        df = pd.DataFrame(rows)
                        df["start_time"] = pd.to_datetime(df["start_time"])
                        df["end_time"] = pd.to_datetime(df["end_time"])
                        df["duração (h)"] = (
                            (df["end_time"] - df["start_time"]).dt.total_seconds() / 3600
                        ).round(1)
                        st.dataframe(
                            df[["start_time", "end_time", "duração (h)"]],
                            use_container_width=True,
                        )
                    else:
                        st.caption("Nenhum jejum registrado ainda.")
                except Exception as e:
                    st.warning(f"Não foi possível carregar os jejuns: {e}")

                with st.expander("Protocolos comuns de jejum"):
                    st.markdown(
                        """
                    - **16/8** → jejum de 16h, janela de alimentação 8h (mais popular)  
                    - **14/10** → mais flexível, bom para iniciantes  
                    - **20/4 (Warrior Diet)** → jejum de 20h, alimentação em 4h  
                    - **24h (1–2x por semana)** → usado em contextos avançados  

                    🔑 *Dicas:*  
                    - Mantenha hidratação adequada durante o jejum (água, café, chá sem açúcar).  
                    - Evite exageros na janela de alimentação.  
                    - Sempre ajuste ao seu contexto de treino/objetivo.  
                    """
                    )
        else:
            st.info("Faça login para registrar seu jejum.")

        # ===== DIÁRIO ALIMENTAR =====
        st.subheader("📒 Diário alimentar")

        session = st.session_state.get("sb_session")
        if not session:
            st.info("Faça login para registrar e visualizar seu diário.")
        else:
            uid = session.user.id

            # Seleção de data
            col_d1, col_d2 = st.columns([1, 2])
            with col_d1:
                ref_date = st.date_input("Data", value=datetime.today().date())
            with col_d2:
                st.caption("Atalho por dia da semana")
                dia_semana = st.radio(
                    "Dias",
                    ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"],
                    horizontal=True,
                    label_visibility="collapsed",
                )
                if st.button("Ir para último registro deste dia da semana", key="btn_ir_ultimo_registro"):
                    try:
                        map_pg = {
                            "Segunda": 1,
                            "Terça": 2,
                            "Quarta": 3,
                            "Quinta": 4,
                            "Sexta": 5,
                            "Sábado": 6,
                            "Domingo": 7,
                        }
                        resp_last = supabase.rpc(
                            "exec_sql",
                            {
                                "sql": f"""
                                select ref_date
                                from public.food_diary
                                where user_id = '{uid}'
                                and extract(isodow from ref_date) = {map_pg[dia_semana]}
                            order by ref_date desc
                                limit 1
                            """
                            },
                        ).execute()
                    except Exception:
                        pass

            st.divider()

            # 💧 Controle de Água no Diário
            # ============================
            # 💧 Água (MVP simples: somente sessão, sem banco/histórico)
            COPOS_ML = 250

            if "agua_ml" not in st.session_state:
                st.session_state.agua_ml = 0

            peso_user = st.session_state.get("ob_w", 70)  # do onboarding, se existir
            meta_ml = int(peso_user * 35) if peso_user else 2000

            st.subheader("💧 Consumo de Água")

            col1, col2, col3 = st.columns([1, 2, 2])

            with col1:
                if st.button("➖", key="agua_menos"):
                    st.session_state.agua_ml = max(0, st.session_state.agua_ml - COPOS_ML)
                if st.button("➕", key="agua_mais"):
                    st.session_state.agua_ml += COPOS_ML

            with col2:
                num_copos = st.session_state.agua_ml // COPOS_ML
                st.write(f"Total: **{st.session_state.agua_ml} ml**")
                st.markdown("".join(["🥛 " for _ in range(num_copos)]) or "—")

            with col3:
                valor = st.number_input("Digite total (ml)", min_value=0, step=250,
                                        value=st.session_state.agua_ml)
                if valor != st.session_state.agua_ml:
                    st.session_state.agua_ml = valor

            pct = st.session_state.agua_ml / meta_ml if meta_ml else 0
            st.progress(min(1.0, pct))
            st.caption(f"Meta diária: {meta_ml} ml")

            st.divider()

            # ===== Alimento rápido (offline) =====
            st.markdown("#### ⚡ Adicionar alimento rápido (offline)")
            _LOCAL_DB = {
                # kcal, p, c, f por 100 g (aprox. cozidos / uso comum BR)
                "frango grelhado":   {"kcal":165, "p":31.0, "c":0.0,  "f":3.6},
                "arroz branco":      {"kcal":130, "p":2.7,  "c":28.0, "f":0.3},
                "arroz integral":    {"kcal":111, "p":2.6,  "c":23.0, "f":0.9},
                "feijão cozido":     {"kcal":95,  "p":6.0,  "c":17.0, "f":0.5},
                "batata doce coz.":  {"kcal":86,  "p":1.6,  "c":20.0, "f":0.1},
                "ovo cozido":        {"kcal":155, "p":13.0, "c":1.1,  "f":11.0},
                "aveia (flocos)":    {"kcal":389, "p":16.9, "c":66.0, "f":6.9},
                "abacate":           {"kcal":160, "p":2.0,  "c":9.0,  "f":15.0},
                "banana prata":      {"kcal":89,  "p":1.1,  "c":23.0, "f":0.3},
                "pão francês":       {"kcal":270, "p":9.0,  "c":57.0, "f":3.0},
            }

            colq1, colq2, colq3 = st.columns([2,1,1])
            with colq1:
                food_q = st.selectbox("Alimento", sorted(_LOCAL_DB.keys()))
            with colq2:
                grams_q = st.number_input("Gramas", min_value=0.0, step=5.0, value=100.0)
            with colq3:
                meal_q = st.selectbox("Refeição", ["Café da manhã","Almoço","Jantar","Lanche","Pré-treino","Pós-treino","Outra"], index=1)

            if st.button("➕ Adicionar alimento rápido", key="btn_add_alimento_rapido"):
                info = _LOCAL_DB.get(food_q)
                factor = grams_q / 100.0
                kcal_q = info["kcal"] * factor
                p_q = info["p"] * factor
                c_q = info["c"] * factor
                f_q = info["f"] * factor

                refeicao_id = salvar_refeicao_no_supabase(
                    uid,
                    str(ref_date),
                    meal_q,
                    food_q,
                    grams_q,
                    kcal_q,
                    p_q,
                    c_q,
                    f_q,
                    None
                )

                if refeicao_id:
                    st.success("Refeição registrada com sucesso!")
                    if add_points(uid, "add_meal", event_key=str(refeicao_id)):
                        award_badge(uid, "Primeira refeição registrada")
                        st.toast("🪙 +2 FC ganhos!")
                        st.success("🎖️ Você desbloqueou a missão: Primeira refeição concluída")

            # ====== IA: Analisar foto do prato (beta) ======
            if st.secrets.get("ENABLE_AI", "false").lower() == "true" and st.secrets.get("OPENROUTER_API_KEY"):
                st.markdown("#### 🤖 Analisar foto do prato (beta)")

                # Padrão: revisão (auto desativado)
                auto_mode = st.checkbox("Analisar e salvar automaticamente (sem revisão)", value=False)

                # 1) entrada de imagem: câmera OU upload
                cam_pic = st.camera_input("Tirar foto do prato (opcional)")
                ai_file = st.file_uploader(
                    "…ou enviar foto da galeria",
                    type=["jpg", "jpeg", "png"],
                    accept_multiple_files=False,
                    key="ai_meal_photo",
                )

                # Prioridade: câmera > upload
                img_src_file = cam_pic if cam_pic is not None else ai_file

                # Função interna: processa IA e salva (auto) ou exibe editor (revisão)
                def _process_and_save(img_url: str, ai_path: str, ref_date, uid, auto: bool):
                    with st.spinner("Analisando imagem com IA..."):
                        items = ai_detect_foods_from_image_openrouter(img_url)

                    if not items:
                        st.warning("Não consegui identificar nada com confiança suficiente. Tente outra foto/ângulo/luz.")
                        return

                    enriched = []
                    for it in items:
                        per100 = lookup_macros_per_100g(it["food"])
                        grams = it["grams"]
                        conf = it["confidence"]
                        if per100:
                            mac = scale_macros(per100, grams)
                            enriched.append(
                                {
                                    "Alimento": it["food"],
                                    "Gramas": round(grams, 0),
                                    "Kcal": round(mac["kcal"], 0),
                                    "Prot (g)": round(mac["p"], 1),
                                    "Carb (g)": round(mac["c"], 1),
                                    "Gord (g)": round(mac["f"], 1),
                                    "Confiança": round(conf, 2),
                                }
                            )
                        else:
                            enriched.append(
                                {
                                    "Alimento": it["food"],
                                    "Gramas": round(grams, 0),
                                    "Kcal": None,
                                    "Prot (g)": None,
                                    "Carb (g)": None,
                                    "Gord (g)": None,
                                    "Confiança": round(conf, 2),
                                }
                            )

                    import pandas as pd
                    df_ai = pd.DataFrame(enriched)

                    if auto:
                        # === AUTO: salva direto no diário ===
                        try:
                            rows_to_insert = []
                            for _, r in df_ai.iterrows():
                                rows_to_insert.append(
                                    {
                                        "user_id": uid,
                                        "ref_date": str(ref_date),
                                        "meal_type": "IA (auto)",
                                        "description": r["Alimento"],
                                        "qty_g": float(r["Gramas"]) if pd.notnull(r["Gramas"]) else None,
                                        "kcal": float(r["Kcal"]) if pd.notnull(r["Kcal"]) else None,
                                        "protein_g": float(r["Prot (g)"]) if pd.notnull(r["Prot (g)"]) else None,
                                        "carbs_g": float(r["Carb (g)"]) if pd.notnull(r["Carb (g)"]) else None,
                                        "fat_g": float(r["Gord (g)"]) if pd.notnull(r["Gord (g)"]) else None,
                                        "photo_path": ai_path,
                                    }
                                )
                            if rows_to_insert:
                                supabase.table("food_diary").insert(rows_to_insert).execute()
                                tot_k = float((df_ai["Kcal"].fillna(0)).sum())
                                tot_p = float((df_ai["Prot (g)"].fillna(0)).sum())
                                tot_c = float((df_ai["Carb (g)"].fillna(0)).sum())
                                tot_f = float((df_ai["Gord (g)"].fillna(0)).sum())
                                st.success(f"Itens adicionados automaticamente: {len(rows_to_insert)}")
                                st.caption(
                                    f"Totais estimados — Kcal {tot_k:.0f} • P {tot_p:.0f} g • C {tot_c:.0f} g • G {tot_f:.0f} g"
                                )
                        except Exception as e:
                            st.error(f"Erro ao salvar (auto): {e}")
                        return

                    # === REVISÃO: editor + botão salvar ===
                    st.markdown("**Revise/ajuste antes de salvar:**")
                    edited = st.data_editor(
                        df_ai,
                        use_container_width=True,
                        num_rows="dynamic",
                        key="ai_meal_editor",
                        column_config={
                            "Alimento": st.column_config.TextColumn(width="medium"),
                            "Gramas": st.column_config.NumberColumn(min_value=0, step=5),
                            "Kcal": st.column_config.NumberColumn(step=5),
                            "Prot (g)": st.column_config.NumberColumn(step=0.5),
                            "Carb (g)": st.column_config.NumberColumn(step=0.5),
                            "Gord (g)": st.column_config.NumberColumn(step=0.5),
                            "Confiança": st.column_config.NumberColumn(min_value=0, max_value=1, step=0.01, disabled=True),
                        },
                    )

                    tot_k = float((edited["Kcal"].fillna(0)).sum())
                    tot_p = float((edited["Prot (g)"].fillna(0)).sum())
                    tot_c = float((edited["Carb (g)"].fillna(0)).sum())
                    tot_f = float((edited["Gord (g)"].fillna(0)).sum())
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Kcal (estim.)", f"{tot_k:,.0f}")
                    c2.metric("Prot (g)", f"{tot_p:,.0f}")
                    c3.metric("Carb (g)", f"{tot_c:,.0f}")
                    c4.metric("Gord (g)", f"{tot_f:,.0f}")

                    if st.button("✅ Adicionar itens ao diário (esta data)", key="btn_add_itens_diario"):
                        try:
                            rows_to_insert = []
                            for _, r in edited.iterrows():
                                rows_to_insert.append(
                                    {
                                        "user_id": uid,
                                        "ref_date": str(ref_date),
                                        "meal_type": "IA (estimativa)",
                                        "description": r["Alimento"],
                                        "qty_g": float(r["Gramas"]) if pd.notnull(r["Gramas"]) else None,
                                        "kcal": float(r["Kcal"]) if pd.notnull(r["Kcal"]) else None,
                                        "protein_g": float(r["Prot (g)"]) if pd.notnull(r["Prot (g)"]) else None,
                                        "carbs_g": float(r["Carb (g)"]) if pd.notnull(r["Carb (g)"]) else None,
                                        "fat_g": float(r["Gord (g)"]) if pd.notnull(r["Gord (g)"]) else None,
                                        "photo_path": ai_path,
                                    }
                                )
                            if rows_to_insert:
                                supabase.table("food_diary").insert(rows_to_insert).execute()
                                st.success("Itens adicionados ao diário! Role a página para ver a listagem do dia.")
                        except Exception as e:
                            st.error(f"Erro ao salvar no diário: {e}")

                # 2) se houver imagem (câmera ou upload), sobe pro Storage e processa
                if img_src_file is not None:
                    import io
                    import datetime as _dt

                    # nome seguro e caminho
                    y_m = _dt.datetime.now().strftime("%Y-%m")
                    d_hms = _dt.datetime.now().strftime("%d-%H%M%S")
                    has_name = hasattr(img_src_file, "name") and img_src_file.name
                    safe_name = (img_src_file.name if has_name else "camera.jpg").replace(" ", "_").lower()
                    ai_path = f"{uid}/ai-meals/{y_m}/{d_hms}-{safe_name}"

                    # bytes: camera_input usa getvalue(); uploader tem .read() (mas Streamlit normaliza .getvalue())
                    try:
                        file_bytes = img_src_file.getvalue() if hasattr(img_src_file, "getvalue") else img_src_file.read()
                    except Exception:
                        file_bytes = None

                    img_url = None
                    try:
                        supabase.storage.from_("progress-photos").upload(
                            path=ai_path,
                            file=io.BytesIO(file_bytes),
                            file_options={"contentType": "image/jpeg", "upsert": False},
                        )
                        signed = supabase.storage.from_("progress-photos").create_signed_url(ai_path, 3600)
                        img_url = signed.get("signedURL") or signed.get("signed_url")
                    except Exception as e:
                        st.error(f"Falha ao subir/assinar a imagem: {e}")

                    if img_url:
                        # AUTO -> processa imediatamente; REVISÃO -> pede clique
                        if auto_mode:
                            _process_and_save(img_url, ai_path, ref_date, uid, auto=True)
                        else:
                            if st.button("Analisar com IA", key="btn_analisar_ia"):
                                _process_and_save(img_url, ai_path, ref_date, uid, auto=False)
            else:
                st.caption("IA de foto desativada (sem custos). Para ativar, defina ENABLE_AI='true' e informe OPENROUTER_API_KEY em secrets.toml.")

            # ===== FORMULÁRIO =====
            with st.form("food_form"):
                c_top1, c_top2 = st.columns(2)
                with c_top1:
                    meal_type = st.selectbox(
                        "Refeição",
                        [
                            "Café da manhã",
                            "Almoço",
                            "Jantar",
                            "Lanche",
                            "Pré-treino",
                            "Pós-treino",
                            "Outra",
                        ],
                        index=1,
                    )
                with c_top2:
                    qty_g = st.number_input(
                        "Quantidade (g) — opcional", min_value=0.0, step=1.0, value=0.0
                    )

                description = st.text_area(
                    "O que você comeu?",
                    placeholder="Ex.: 150g frango, 120g arroz, salada...",
                )

                c_mac1, c_mac2, c_mac3, c_kcal = st.columns(4)
                with c_mac1:
                    protein_g = st.number_input(
                        "Proteína (g)", min_value=0.0, step=1.0, value=0.0
                    )
                with c_mac2:
                    carbs_g = st.number_input(
                        "Carboidratos (g)", min_value=0.0, step=1.0, value=0.0
                    )
                with c_mac3:
                    fat_g = st.number_input(
                        "Gorduras (g)", min_value=0.0, step=0.5, value=0.0
                    )
                with c_kcal:
                    kcal = st.number_input(
                        "Kcal (opcional)",
                        min_value=0.0,
                        step=1.0,
                        value=0.0,
                        help="Se deixar 0, calculo automático: 4p + 4c + 9g",
                    )

                # FOTO do prato (agora dentro do form)
                photo_file = st.file_uploader(
                    "Foto do prato (opcional)",
                    type=["png", "jpg", "jpeg"],
                    accept_multiple_files=False,
                    key="meal_photo",
                )

                add_meal = st.form_submit_button("➕ Adicionar refeição")

            # ===== SALVAR =====
            if add_meal:
                kcal_val = (
                    float(kcal)
                    if kcal and kcal > 0
                    else (protein_g * 4 + carbs_g * 4 + fat_g * 9)
                )
                photo_path = None
                try:
                    if photo_file is not None:
                        import datetime as _dt

                        y_m = _dt.datetime.now().strftime("%Y-%m")
                        d_hms = _dt.datetime.now().strftime("%d-%H%M%S")
                        safe_name = photo_file.name.replace(" ", "_").lower()
                        photo_path = f"{uid}/meals/{y_m}/{d_hms}-{safe_name}"
                        supabase.storage.from_("progress-photos").upload(
                            path=photo_path,
                            file=photo_file,
                            file_options={
                                "contentType": photo_file.type or "image/jpeg",
                                "upsert": False,
                            },
                        )
                except Exception as e:
                    st.warning(f"Falha ao subir a foto do prato: {e}")

                try:
                    supabase.table("food_diary").insert(
                        {
                            "user_id": uid,
                            "ref_date": str(ref_date),
                            "meal_type": meal_type,
                            "description": description.strip() or None,
                            "qty_g": float(qty_g) if qty_g else None,
                            "kcal": float(kcal_val) if kcal_val else None,
                            "protein_g": float(protein_g) if protein_g else None,
                            "carbs_g": float(carbs_g) if carbs_g else None,
                            "fat_g": float(fat_g) if fat_g else None,
                            "photo_path": photo_path,
                        }
                    ).execute()
                    st.success("Refeição adicionada!")
                except Exception as e:
                    st.error(f"Erro ao salvar refeição: {e}")

            # ===== LISTAGEM =====
            try:
                resp = (
                    supabase.table("food_diary")
                    .select("*")
                    .eq("user_id", uid)
                    .eq("ref_date", str(ref_date))
                    .order("created_at", desc=False)
                    .execute()
                )
                rows = resp.data or []
            except Exception as e:
                rows = []
                st.error(f"Erro ao carregar diário: {e}")

            if not rows:
                st.caption("Nenhuma refeição registrada para esta data.")
            else:
                import pandas as pd

                df = pd.DataFrame(rows)

                # Totais
                total_kcal = float(df["kcal"].fillna(0).sum())
                total_p = float(df["protein_g"].fillna(0).sum())
                total_c = float(df["carbs_g"].fillna(0).sum())
                total_f = float(df["fat_g"].fillna(0).sum())

                st.markdown("### Total do dia")
                c_tot1, c_tot2, c_tot3, c_tot4 = st.columns(4)
                c_tot1.metric("Kcal", f"{total_kcal:,.0f}")
                c_tot2.metric("Proteína", f"{total_p:,.0f} g")
                c_tot3.metric("Carbo", f"{total_c:,.0f} g")
                c_tot4.metric("Gordura", f"{total_f:,.0f} g")

                # Progresso vs metas
                kcal_meta = st.session_state.get("kcal_alvo")
                p_meta = st.session_state.get("prot_g")
                c_meta = st.session_state.get("carb_g")
                f_meta = st.session_state.get("gord_g")
                if all(v is not None for v in [kcal_meta, p_meta, c_meta, f_meta]):
                    st.markdown("#### Progresso vs meta do dia")
                    st.progress(
                        min(total_kcal / kcal_meta, 1.0),
                        text=f"Kcal: {int(total_kcal)}/{int(kcal_meta)}",
                    )
                    st.progress(
                        min(total_p / p_meta, 1.0),
                        text=f"Proteína: {int(total_p)}/{int(p_meta)} g",
                    )
                    st.progress(
                        min(total_c / c_meta, 1.0),
                        text=f"Carbo: {int(total_c)}/{int(c_meta)} g",
                    )
                    st.progress(
                        min(total_f / f_meta, 1.0),
                        text=f"Gordura: {int(total_f)}/{int(f_meta)} g",
                    )

                st.markdown("### Refeições")
                show_df = df[
                    [
                        "created_at",
                        "meal_type",
                        "description",
                        "qty_g",
                        "kcal",
                        "protein_g",
                        "carbs_g",
                        "fat_g",
                    ]
                ].copy()
                show_df.rename(
                    columns={
                        "created_at": "Quando",
                        "meal_type": "Refeição",
                        "description": "Descrição",
                        "qty_g": "Qtd (g)",
                        "kcal": "Kcal",
                        "protein_g": "Prot (g)",
                        "carbs_g": "Carb (g)",
                        "fat_g": "Gord (g)",
                    },
                    inplace=True,
                )
                st.dataframe(show_df, use_container_width=True)

                # Fotos
                st.markdown("#### Fotos das refeições do dia")
                thumbs = [r for r in rows if r.get("photo_path")]
                if not thumbs:
                    st.caption("Nenhuma foto enviada hoje.")
                else:
                    cols = st.columns(3)
                    for i, r in enumerate(thumbs):
                        try:
                            signed = supabase.storage.from_(
                                "progress-photos"
                            ).create_signed_url(r["photo_path"], 3600)
                            url = signed.get("signedURL") or signed.get("signed_url")
                            if url:
                                with cols[i % 3]:
                                    _show_image(url)
                                    st.caption(f"{r['meal_type']} — {r['created_at'][:16]}")

                        except Exception as e:
                            st.warning(
                                f"Não foi possível exibir a foto de {r.get('meal_type','?')}: {e}"
                            )

                # Deletar
                with st.expander("Apagar alguma refeição?"):
                    ids = [
                        (
                            r["id"],
                            f'{r["meal_type"]} - {r.get("description","")} ({r["created_at"][:16]})',
                        )
                        for r in rows
                    ]
                    if ids:
                        sel = st.selectbox(
                            "Selecione para apagar", ids, format_func=lambda x: x[1]
                        )
                        if st.button("🗑️ Apagar selecionado", key="btn_apagar_selecionado"):
                            try:
                                supabase.table("food_diary").delete().eq(
                                    "id", sel[0]
                                ).execute()
                                st.success(
                                    "Apagado. Atualize a página para ver a lista atualizada."
                                )
                            except Exception as e:
                                st.error(f"Erro ao apagar: {e}")

    with aba_dash:
        st.subheader("📈 Evolução do peso corporal")

        session = st.session_state.get("sb_session")
        if not session:
            st.info("Faça login para visualizar seu progresso de peso.")
        else:
            uid = session.user.id

            # === Registrar peso (sempre liberado) ===
            st.markdown("### ⚖️ Registrar peso da semana")
            col_p1, col_p2 = st.columns([2, 1])
            with col_p1:
                new_weight = st.number_input("Peso atual (kg)", min_value=30.0, max_value=300.0, step=0.1)
            with col_p2:
                if st.button("💾 Salvar peso", key="btn_salvar_peso"):
                    try:
                        supabase.table("weight_logs").insert({
                            "user_id": uid,
                            "ref_date": str(date.today()),
                            "weight_kg": float(new_weight)
                        }).execute()
                        st.success("Peso registrado com sucesso!")
                        if add_points(uid, "add_weight", event_key=str(date.today())):
                            award_badge(uid, "Primeiro peso registrado")
                            st.toast("🪙 +1 FC ganho!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao salvar peso: {e}")

            st.divider()

            # === Histórico de pesos ===
            try:
                resp = (
                    supabase.table("weight_logs")
                    .select("ref_date, weight_kg")
                    .eq("user_id", uid)
                    .order("ref_date", desc=False)
                    .execute()
                )

                rows = resp.data or []
                if not rows:
                    st.caption("Ainda não há pesos registrados.")
                else:
                    import pandas as pd
                    df = pd.DataFrame(rows)
                    df["ref_date"] = pd.to_datetime(df["ref_date"]).dt.date
                    df = df.dropna(subset=["weight_kg"]).sort_values("ref_date")

                    atual = float(df["weight_kg"].iloc[-1])
                    primeiro = float(df["weight_kg"].iloc[0])
                    delta = atual - primeiro

                    m1, m2, m3 = st.columns(3)
                    m1.metric("Peso atual", f"{atual:,.1f} kg")
                    m2.metric("Peso inicial", f"{primeiro:,.1f} kg")
                    m3.metric("Variação", f"{delta:+.1f} kg")

                    st.line_chart(data=df.set_index("ref_date")["weight_kg"], height=300)

                    with st.expander("📋 Ver dados"):
                        st.dataframe(
                            df.rename(columns={"ref_date": "Data", "weight_kg": "Peso (kg)"}),
                            use_container_width=True,
                        )
            except Exception as e:
                st.error(f"Erro ao carregar pesos: {e}")

            # === Extra: lembrete semanal ===
            if rows:
                ultima_data = df["ref_date"].iloc[-1]
                dias_passados = (date.today() - ultima_data).days
                if dias_passados >= 7:
                    st.warning(f"⚠️ Último peso registrado há {dias_passados} dias. Hora de atualizar!")

            # === Follow-up completo (apenas coaching) ===
            if is_user_coaching(uid):
                st.divider()
                st.subheader("📊 Seu Check-in semanal completo")
                st.info("Acesse a aba **📊 Check-in Semanal** para preencher sono, estresse, adesão e outros fatores.")

# set_page_config, secrets, splash_once()

# estados (nav, sb_session), supabase client, helpers...

# render_auth_gate()
# render_app_calorias()
# (não precisa definir render_receitas/render_perfil se usa multipage com switch_page)

# --- Roteador (ÚNICO) ---
def render_auth_gate():
    st.markdown(
        """
        <div style='text-align: center; padding: 1rem 0;'>
            <h1 style='color: #2BAEAE;'>🔐 Acesse sua conta</h1>
            <p style='color: #6C757D;'>Entre com suas credenciais para continuar</p>
        </div>
        """,
        unsafe_allow_html=True
    )

    col_spacer1, col_form, col_spacer2 = st.columns([1, 2, 1])
    with col_form:
        if st.button("← Voltar", type="secondary", use_container_width=True):
            st.session_state["show_login"] = False
            st.rerun()

        st.write("")
        
        default_email = st.session_state.get("saved_email", "")
        email = st.text_input("E-mail", value=default_email, key="login_email", placeholder="seu@email.com")
        password = st.text_input("Senha", type="password", key="login_password", placeholder="Sua senha")
        remember = st.checkbox("Lembrar meu login", value=True, key="login_remember")

        st.write("")

        if st.button("🚀 Entrar", key="btn_do_login", use_container_width=True, type="primary"):
            if not email or not password:
                st.error("Por favor, preencha e-mail e senha.")
            else:
                try:
                    from helpers import supabase
                    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    user = getattr(res, "user", None) or (res.get("user") if isinstance(res, dict) else None)

                    if user:
                        st.session_state["sb_session"] = res
                        st.session_state["user_id"] = user.id
                        st.session_state["user_email"] = user.email

                        try:
                            from helpers import db_upsert_profile
                            db_upsert_profile(user.id, user.email)
                        except Exception:
                            pass

                        if remember:
                            st.session_state["saved_email"] = email

                        st.session_state["show_login"] = False
                        st.success("✅ Login realizado com sucesso!")
                        st.rerun()
                    else:
                        st.error("Falha no login. Verifique suas credenciais.")
                except Exception as e:
                    st.error(f"Erro ao fazer login: {e}")
        
        st.markdown(
            """
            <div style='text-align: center; margin-top: 1.5rem; padding: 1rem; background-color: #F8F9FA; border-radius: 8px;'>
                <p style='color: #6C757D; font-size: 0.9rem; margin: 0;'>
                    Não tem uma conta? <a href='#' style='color: #FF7A3D; text-decoration: none; font-weight: 600;'>Criar conta grátis</a>
                </p>
            </div>
            """,
            unsafe_allow_html=True
        )


def render_logout():
    if st.button("Sair", type="secondary", use_container_width=True):
        try:
            from helpers import supabase
            supabase.auth.sign_out()
        except Exception:
            pass

        # limpa sessão mas mantém email salvo (se existir)
        for k in ["sb_session", "user_id", "user_email", "plan_id", "plan_name", "plan_inicio", "plan_fim"]:
            st.session_state.pop(k, None)

        st.success("Sessão encerrada.")
        st.rerun()

def render_router():
    session = st.session_state.get("sb_session")

    if not session:
        # 🔒 Se o usuário pediu login, mantenha a tela aberta
        if st.session_state.get("show_login"):
            render_auth_gate()
            st.stop()

        # Se o onboarding foi iniciado, continue nele
        if st.session_state.get("onboarding_started"):
            render_onboarding(uid=None, profile={})
            return

        # Tela inicial com design melhorado
        st.markdown(
            """
            <div style='text-align: center; padding: 2rem 0;'>
                <h1 style='color: #2BAEAE; font-size: 2.5rem; margin-bottom: 0.5rem;'>🍽️ Bem-vindo ao calorIA</h1>
                <p style='font-size: 1.2rem; color: #6C757D; margin-bottom: 2rem;'>
                    Contar calorias ficou fácil com o poder da IA
                </p>
            </div>
            """,
            unsafe_allow_html=True
        )

        col_spacer1, col_center, col_spacer2 = st.columns([1, 2, 1])
        with col_center:
            if st.button("🚀 Começar agora (criar conta)", use_container_width=True, type="primary"):
                st.session_state.onboarding_started = True
                st.session_state.ob_step = 0
                st.rerun()

            st.write("")
            
            if st.button("🔑 Já tenho conta → Login", use_container_width=True, key="btn_login"):
                st.session_state["show_login"] = True
                st.rerun()
        
        st.markdown(
            """
            <div style='text-align: center; margin-top: 3rem; padding: 2rem; background-color: #F8F9FA; border-radius: 10px;'>
                <h3 style='color: #2BAEAE;'>✨ Por que escolher o calorIA?</h3>
                <div style='display: flex; flex-wrap: wrap; justify-content: center; gap: 2rem; margin-top: 1.5rem;'>
                    <div style='flex: 1; min-width: 200px; max-width: 300px;'>
                        <div style='font-size: 2rem; margin-bottom: 0.5rem;'>🤖</div>
                        <strong>IA Inteligente</strong>
                        <p style='color: #6C757D; font-size: 0.9rem;'>Reconhecimento automático de alimentos por foto</p>
                    </div>
                    <div style='flex: 1; min-width: 200px; max-width: 300px;'>
                        <div style='font-size: 2rem; margin-bottom: 0.5rem;'>📊</div>
                        <strong>Acompanhamento Completo</strong>
                        <p style='color: #6C757D; font-size: 0.9rem;'>Gráficos de evolução e metas personalizadas</p>
                    </div>
                    <div style='flex: 1; min-width: 200px; max-width: 300px;'>
                        <div style='font-size: 2rem; margin-bottom: 0.5rem;'>🍱</div>
                        <strong>Receitas Exclusivas</strong>
                        <p style='color: #6C757D; font-size: 0.9rem;'>Cardápios balanceados e deliciosos</p>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
        return


    # ✅ Só executa o restante se houver sessão (usuário logado)
    try:
        uid = session.user.id
    except Exception:
        uid = None

    # 🔹 Checa onboarding
    try:
        resp = supabase.table("profiles").select("*").eq("id", uid).single().execute()
        profile = resp.data or {}
    except Exception:
        profile = {}

    if not profile.get("onboarding_done"):
        render_onboarding(uid, profile)
        st.stop()

    # 🔹 define nav
    nav = st.session_state.get("nav", "app")

    # 🔹 controla visibilidade das abas
    coaching = is_user_coaching(uid)

    if nav == "conquistas":
        render_conquistas()
    elif nav == "home":
        st.subheader("Bem-vindo!")
        st.write("Escolha uma opção no menu lateral para começar.")
    elif nav == "app":
        render_app_calorias()
    elif nav == "follow" and coaching:   # só pacientes ativos veem
        render_followup()
    else:
        render_app_calorias()

def render_conquistas():
    st.header("🏆 Conquistas")

    session = st.session_state.get("sb_session")
    if not session:
        st.warning("Faça login para ver suas conquistas.")
        return
    uid = session.user.id

    row = get_points(uid)
    pts = row.get("points", 0)
    badges = row.get("badges", [])

    # Cabeçalho
    st.subheader(f"Saldo atual: {pts} FC")
    st.progress(min(pts % 100 / 100, 1.0))  # barra rumo ao próximo “nível” (100 FC)

    # Badges
    st.markdown("### Suas Missões")
    if badges:
        for b in badges:
            st.write(f"- **{b.get('name')}** — {b.get('date')[:10]}")
    else:
        st.info("Sem missões concluídas ainda. Bora conquistar a primeira?")

    # Como ganhar pontos
    st.markdown("### Como ganhar FC")
    st.write(
        """
        - ✅ Login diário: **+1 FC**
        - 🍽️ Lançar refeição: **+2 FC**
        - 📷 Medidas / foto: **+3 FC**
        - 🎂 Aniversário: **+10 FC**
        - ⭐ Avaliar o app na loja: **+20 FC**
        - 🤝 Indicar e a pessoa assinar: **+50 FC**
        - 📝 Check-in / Follow-up: **+5 FC**
        """
    )

# >>> PONTO DE ENTRADA DA UI <<<
render_router()

# --- Sidebar enxuta (pode ficar aqui) ---
st.sidebar.title("📋 Menu")
st.sidebar.page_link("app_calorias.py", label="🏠 Início")
st.sidebar.page_link("pages/06_Receitas.py", label="🍽️ Receitas")
st.sidebar.page_link("pages/05_Perfil_Conta.py", label="👤 Perfil / Conta")

# 🔹 Só aparece para pacientes ativos
uid = st.session_state.get("user_id")
if uid and is_user_coaching(uid):
    st.sidebar.page_link("pages/07_Follow_Up.py", label="📊 Check-in Semanal")

session_cur = st.session_state.get("sb_session")
if session_cur:
    uid = session_cur.user.id
    try:
        points_row = get_points(uid)
        pts = points_row.get("points", 0)
        st.sidebar.markdown('<div class="sb-title">💰 FC (Fitness Coin)</div>', unsafe_allow_html=True)
        if st.sidebar.button(f"Saldo: {pts} FC", key="sb_points_btn", use_container_width=True):
            st.session_state["nav"] = "conquistas"  # rota oculta
    except Exception:
        st.sidebar.info("Carregando pontos…")

    st.sidebar.header("Atalhos")
    st.sidebar.button("🍽️ Ir para App", key="sb_go_app", on_click=lambda: set_nav("app"), use_container_width=True)
    if st.sidebar.button("🧾 Ir para Receitas", key="sb_go_rec", use_container_width=True):
        st.switch_page("pages/06_Receitas.py")
    if st.sidebar.button("👤 Ir para Perfil", key="sb_go_prof", use_container_width=True):
        st.switch_page("pages/05_Perfil_Conta.py")
else:
    st.sidebar.empty()

session_cur = st.session_state.get("sb_session")
if session_cur:
    st.sidebar.header("Conta")
    st.sidebar.write(f"Logado como: {st.session_state.get('user_email','')}")
    render_logout()
else:
    st.sidebar.info("Não há usuário logado.")






















