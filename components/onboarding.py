# === components/onboarding.py (revisado) ===
import math
from datetime import date
import streamlit as st

# --- Funções auxiliares ---

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
    return (10 * kg) + (6.25 * cm) - (5 * anos) + s


def _tdee(kg, cm, anos, sex, atividade_txt):
    return _bmr_mifflin(kg, cm, anos, sex) * _fator_atividade(atividade_txt)


def _idade_from_dob(dob: date) -> int:
    if not dob:
        return 30
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _normalize_goal(goal_txt: str) -> str:
    if not goal_txt:
        return "Manutenção"
    g = goal_txt.lower().strip()
    if ("emagrecer" in g) or ("perder gordura" in g) or ("definir" in g):
        return "Emagrecer"
    if "ganhar massa" in g:
        return "Ganhar massa"
    return "Manutenção"


def _semanas_para_alvo(peso_atual, peso_meta, objetivo):
    # aproximações conservadoras de ritmo (normalizado)
    objetivo_norm = _normalize_goal(objetivo)
    if objetivo_norm == "Emagrecer":
        perda_por_sem = 0.5
        delta = max(peso_atual - peso_meta, 0.0)
        return 0 if delta <= 0 else math.ceil(delta / perda_por_sem)
    elif objetivo_norm == "Ganhar massa":
        ganho_por_sem = 0.25
        delta = max(peso_meta - peso_atual, 0.0)
        return 0 if delta <= 0 else math.ceil(delta / ganho_por_sem)
    return 0


def _is_authed():
    # considera sessão supabase OU variáveis guardadas na session_state
    try:
        from helpers import supabase
        sess_getter = getattr(supabase.auth, "get_session", None)
        if callable(sess_getter):
            sess = sess_getter()
            if sess:
                return True
    except Exception:
        pass
    return bool(st.session_state.get("user_id") or st.session_state.get("sb_session"))

def _auth_uid_or_none():
    try:
        from helpers import supabase
        sess_getter = getattr(supabase.auth, "get_session", None)
        if callable(sess_getter):
            sess = sess_getter()
            if sess and getattr(sess, "user", None):
                return str(sess.user.id)
    except Exception:
        pass
    return None

def _save_onboarding_and_go_home():
    auid = _auth_uid_or_none()
    if not auid:
        st.warning("Sua sessão expirou. Faça login para concluir.")
        st.session_state.ob_step = 1
        st.session_state.auth_mode = "login"
        st.rerun()

    try:
        goal_to_save = _normalize_goal(goal)

        # 2) update do perfil (RLS: id = auth.uid())
        supabase.table("profiles").update(
            {
                "full_name": full_name or None,
                "dob": str(dob) if dob else None,
                "sex": sex,
                "height_cm": float(height_cm) if height_cm else None,
                "weight_kg": float(weight_kg) if weight_kg else None,
                "goal": goal_to_save,
                "target_weight_kg": float(target_weight_kg) if target_weight_kg else None,
                "obstacles": (st.session_state.get("ob_obs") or "").strip() or None,
                "onboarding_done": True,
            }
        ).eq("id", uid).execute()

        # 3) weight_logs: insere HOJE só se ainda não existir (idempotente)
        today_str = str(date.today())
        exists = supabase.table("weight_logs") \
            .select("id") \
            .eq("user_id", uid) \
            .eq("ref_date", today_str) \
            .limit(1) \
            .execute()
        if not getattr(exists, "data", exists):
            supabase.table("weight_logs").insert({
                "user_id": uid,           # RLS: with check (user_id = auth.uid())
                "ref_date": today_str,
                "weight_kg": float(weight_kg),
            }).execute()

        # 4) terminou → ir para o painel
        st.success("Onboarding concluído! Redirecionando…")
        st.session_state.onboarding_done = True
        # se usa multipage:
        # st.switch_page("pages/01_Diario_Alimentar.py")
        # ou roteador simples:
        st.session_state.route = "home"
        st.rerun()

    except Exception as e:
        st.error(f"Erro ao salvar: {e}")

# === Onboarding (wizard) ===

def render_onboarding(uid: str, profile: dict):
    import pandas as pd
    from helpers import supabase  # import local aqui, visível em toda a função

    st.markdown("### 👋 Boas-vindas ao calorIA")

    if "ob_step" not in st.session_state:
        st.session_state.ob_step = 0  # começa no step 0
    step = st.session_state.ob_step

    # estado temporário (defaults do profile se existirem)
    full_name = st.session_state.get("ob_name", profile.get("full_name", ""))
    email = profile.get("email", "")
    dob = st.session_state.get("ob_dob") or (profile.get("dob") and date.fromisoformat(profile["dob"]))
    sex = st.session_state.get("ob_sex", profile.get("sex", "Masculino"))
    height_cm = st.session_state.get("ob_h", float(profile.get("height_cm") or 170))
    weight_kg = st.session_state.get("ob_w", float(profile.get("weight_kg") or 75))
    atividade = st.session_state.get("ob_act", "Moderado (3–5x/semana)")
    goal = st.session_state.get("ob_goal", profile.get("goal") or "Emagrecer")
    target_weight_kg = st.session_state.get("ob_target", float(profile.get("target_weight_kg") or max(weight_kg - 5, 50)))
    obstacles = st.session_state.get("ob_obs", profile.get("obstacles") or "")

    # === STEP 0: pular direto para cadastro se não autenticado ===
    if step == 0 and not _is_authed():
        st.session_state.ob_step = 1
        st.rerun()

    # === STEP 0 (landing opcional) ===
    if step == 0:
        st.markdown(
            "<h2 style='text-align:center;'>🍽️ Contar calorias ficou fácil com o <b>calorIA</b></h2>",
            unsafe_allow_html=True,
        )
        st.write("")

        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button("🚀 Começar agora", use_container_width=True, key="btn_start"):
                st.session_state.ob_step = 1
                st.rerun()

        st.write("")
        st.markdown(
            "<div style='text-align:center; font-size:14px; color:gray;'>Já tem conta? <a href='#' style='text-decoration:none;'>Faça login</a></div>",
            unsafe_allow_html=True,
        )
        return

    # === STEP 1 — Cadastro/Login ===
    if step == 1:
        st.subheader("👤 Crie sua conta")
        st.write("Use o Google para começar em 1 clique, ou crie com seu e-mail.")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔑 Entrar com Google", use_container_width=True, key="btn_google"):
                try:
                    res = supabase.auth.sign_in_with_oauth({"provider": "google"})
                    st.success("Redirecionando para login do Google…")
                    st.stop()
                except Exception as e:
                    st.error(f"Erro ao conectar com Google: {e}")

        with col2:
            st.markdown("<div style='text-align:center;color:gray;'>ou</div>", unsafe_allow_html=True)

        email_input = st.text_input("E-mail")
        password = st.text_input("Senha", type="password")
        confirm = st.text_input("Confirmar senha", type="password")

        if st.button("📬 Criar conta", use_container_width=True, key="btn_signup"):
            if not email_input or not password:
                st.warning("Preencha o e-mail e a senha.")
            elif password != confirm:
                st.warning("As senhas não coincidem.")
            else:
                try:
                    res = supabase.auth.sign_up({"email": email_input, "password": password})
                    if hasattr(res, "user") and res.user:
                        st.session_state["sb_session"] = res
                        st.session_state["user_id"] = res.user.id
                        st.session_state["user_email"] = res.user.email
                        st.session_state.ob_step = 2
                        st.rerun()
                    else:
                        st.error("Erro ao criar conta. Tente novamente.")
                except Exception as e:
                    st.error(f"Falha no cadastro: {e}")

        st.write("")
        st.markdown(
            "<div style='text-align:center; font-size:14px; color:gray;'>Já tem conta? <a href='#' style='text-decoration:none;' onclick=\"window.location.reload()\">Faça login</a></div>",
            unsafe_allow_html=True,
        )

    # === STEP 2 — Por que o calorIA é diferente ===
    if step == 2:
        st.subheader("📊 Por que o calorIA é diferente?")
        st.write("Veja como o calorIA se compara com outros apps de contar calorias:")

        st.markdown(
            """
        <style>
        .comp-table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        .comp-table th, .comp-table td { border: 1px solid #ddd; padding: 10px; text-align: center; font-size: 14px; }
        .comp-table th { background-color: #f5f5f5; font-weight: bold; }
        .yes { color: #2ecc71; font-weight: bold; }
        .no { color: #e74c3c; font-weight: bold; }
        </style>
        <table class="comp-table">
        <tr><th>Funcionalidade</th><th>Outros Apps</th><th>calorIA</th></tr>
        <tr><td>Contagem de calorias</td><td class="yes">✔️</td><td class="yes">✔️ + IA mais precisa</td></tr>
        <tr><td>Scanner de pratos com IA</td><td class="no">❌</td><td class="yes">✔️</td></tr>
        <tr><td>Receitas e cardápios prontos</td><td class="no">❌</td><td class="yes">✔️</td></tr>
        <tr><td>Relatórios de evolução (peso, medidas, fotos)</td><td class="no">❌</td><td class="yes">✔️</td></tr>
        <tr><td>Lembretes automáticos</td><td class="no">❌</td><td class="yes">✔️</td></tr>
        </table>
        """,
            unsafe_allow_html=True,
        )

        st.info("👉 80% dos usuários do calorIA relatam que conseguem manter resultados no longo prazo — sem efeito sanfona.")

    # === STEP 3 — Dados básicos ===
    if step == 3:
        st.subheader("Seus dados básicos")

        full_name = st.text_input("Nome completo", value=full_name)

        col1, col2 = st.columns(2)
        with col1:
            sex = st.selectbox("Sexo", ["Masculino", "Feminino"], index=0 if sex == "Masculino" else 1)
            dob = st.date_input("Data de nascimento", value=dob or date(1995, 1, 1))

        with col2:
            height_cm = st.number_input("Altura (cm)", min_value=120.0, max_value=230.0, step=0.5, value=float(height_cm))
            weight_kg = st.number_input("Peso atual (kg)", min_value=30.0, max_value=300.0, step=0.1, value=float(weight_kg))
            st.caption("⚖️ Este será seu **peso inicial**, usado para calcular calorias e iniciar seu gráfico de evolução.")

        atividade = st.selectbox(
            "Nível de atividade",
            [
                "Sedentário (pouco ou nenhum exercício)",
                "Leve (1–3x/semana)",
                "Moderado (3–5x/semana)",
                "Alto (6–7x/semana)",
                "Atleta/Extremo (2x/dia)",
            ],
            index=[
                "Sedentário (pouco ou nenhum exercício)",
                "Leve (1–3x/semana)",
                "Moderado (3–5x/semana)",
                "Alto (6–7x/semana)",
                "Atleta/Extremo (2x/dia)",
            ].index(atividade),
        )

    # === STEP 4 — Objetivo, IMC e projeção ===
    if step == 4:
        st.subheader("🎯 Seu objetivo e progresso inicial")

        col1, col2 = st.columns(2)
        with col1:
            idade = _idade_from_dob(dob or date(1995, 1, 1))
            st.metric("Idade", f"{idade} anos")
            imc = round(weight_kg / ((height_cm / 100) ** 2), 1)
            st.metric("IMC atual", f"{imc}")

            if imc < 18.5:
                st.caption("🔹 Abaixo do peso — vamos trabalhar ganho de massa e força.")
            elif imc < 25:
                st.caption("🟢 Faixa saudável — foco em manter e evoluir performance.")
            elif imc < 30:
                st.caption("🟠 Leve sobrepeso — ótimo momento pra ajustar rotina.")
            else:
                st.caption("🔴 Acima do peso — pequenas mudanças já trarão grandes resultados.")

        with col2:
            st.markdown("**Como você se sente com seu corpo hoje?**")
            mood = st.radio("", ["💤 Cansado", "🙂 Normal", "💪 Motivado"], horizontal=True)
            st.session_state["mood_today"] = mood

        st.divider()
        st.subheader("Qual é seu objetivo principal?")
        goal = st.selectbox(
            "",
            ["Emagrecer", "Definir / Perder gordura", "Ganhar massa muscular", "Saúde e energia"],
            index=["Emagrecer", "Definir / Perder gordura", "Ganhar massa muscular", "Saúde e energia"].index(goal)
            if goal in ["Emagrecer", "Definir / Perder gordura", "Ganhar massa muscular", "Saúde e energia"]
            else 0,
        )

        st.divider()
        st.subheader("🏁 Peso meta")
        target_weight_kg = st.number_input(
            "Qual peso você quer atingir?",
            min_value=30.0,
            max_value=300.0,
            step=0.1,
            value=float(target_weight_kg),
        )

        delta = weight_kg - target_weight_kg
        goal_norm = _normalize_goal(goal)
        semanas = _semanas_para_alvo(weight_kg, target_weight_kg, goal_norm)

        if delta > 0:
            st.success(f"Perder **{abs(delta):.1f} kg** é uma meta realista 💪")
        elif delta < 0:
            st.info(f"Ganhar **{abs(delta):.1f} kg** é possível com constância 🏋️‍♂️")
        else:
            st.caption("Manter o peso atual também é uma jornada importante 🙂")

        st.caption("✨ 90% dos usuários do **calorIA** mantêm seus resultados após 6 meses.")

        # --- Gráfico visual de projeção ---
        import altair as alt

        if semanas > 0:
            if goal_norm == "Emagrecer":
                passo = (weight_kg - target_weight_kg) / max(semanas, 1)
                serie = [weight_kg - i * passo for i in range(semanas + 1)]
            elif goal_norm == "Ganhar massa":
                passo = (target_weight_kg - weight_kg) / max(semanas, 1)
                serie = [weight_kg + i * passo for i in range(semanas + 1)]
            else:
                serie = [weight_kg] * (semanas + 1)

            df = pd.DataFrame({"Semana": list(range(len(serie))), "Peso (kg)": serie})

            chart = (
                alt.Chart(df)
                .mark_line(color="#2BAEAE", point=True)
                .encode(x="Semana", y="Peso (kg)")
                .properties(height=250)
            )

            st.altair_chart(chart, use_container_width=True)
            st.caption("📈 Visualize sua jornada — cada semana é um passo mais perto do seu melhor físico.")

        st.divider()
        st.session_state.ob_goal = goal
        st.session_state.ob_target = target_weight_kg

    # === STEP 5 — Plano personalizado ===
    if step == 5:
        st.subheader("✨ Seu plano personalizado está sendo criado...")
        st.caption("Estamos calculando tudo com base no seu corpo, rotina e objetivo. Nada genérico aqui 👇")

        with st.spinner("🌀 Analisando metabolismo e nível de atividade..."):
            idade = _idade_from_dob(dob or date(1995, 1, 1))
            bmr = _bmr_mifflin(weight_kg, height_cm, idade, sex)
            tdee_val = _tdee(weight_kg, height_cm, idade, sex, atividade)
            goal_norm = _normalize_goal(goal)
            ajuste = {"Emagrecer": -20, "Ganhar massa": 15, "Manutenção": 0}[goal_norm]
            kcal_alvo = tdee_val * (1 + ajuste / 100.0)
            agua_l = weight_kg * 35.0 / 1000.0

        # 🔹 Bloco visual com métricas
        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        c1.metric("🔥 BMR (Metabolismo basal)", f"{bmr:,.0f} kcal/d")
        c2.metric("⚙️ TDEE (Gasto total)", f"{tdee_val:,.0f} kcal/d")
        c3.metric("🎯 Calorias alvo", f"{kcal_alvo:,.0f} kcal/d")

        st.caption(f"💧 Recomendação de água: cerca de **{agua_l:,.2f} L/dia**")

        # 🔹 Projeção visual do progresso
        semanas = _semanas_para_alvo(weight_kg, target_weight_kg, goal_norm)
        if semanas > 0:
            delta = abs(weight_kg - target_weight_kg)
            st.markdown(f"⏳ Estimativa até a meta: **~{semanas} semanas** para ajustar cerca de **{delta:.1f} kg**.")
            st.progress(0.1)
            st.caption("Visualize seu progresso inicial 👇")

            if goal_norm == "Emagrecer":
                passo = (weight_kg - target_weight_kg) / max(semanas, 1)
                serie = [weight_kg - i * passo for i in range(semanas + 1)]
            elif goal_norm == "Ganhar massa":
                passo = (target_weight_kg - weight_kg) / max(semanas, 1)
                serie = [weight_kg + i * passo for i in range(semanas + 1)]
            else:
                serie = [weight_kg] * (semanas + 1)

            df = pd.DataFrame({"Semana": list(range(len(serie))), "Peso (kg)": serie})
            st.line_chart(df, x="Semana", y="Peso (kg)", use_container_width=True)

            st.success(
                f"🎯 Perder **{delta:.1f} kg** é uma meta realista — 90% dos usuários do calorIA conseguem manter os resultados após 6 meses."
            )
        else:
            st.info("Você já está na meta — agora é foco em **manter** com constância e leveza.")

        # 🔹 Próximo passo (velocidade desejada)
        st.divider()
        st.subheader("🚀 Qual ritmo você prefere?")
        ritmo = st.radio(
            "Escolha seu estilo de progresso:",
            ["Devagar e seguro", "Moderado (equilíbrio)", "Rápido (intensivo)"],
            index=1,
            horizontal=True,
        )

        if ritmo == "Devagar e seguro":
            st.caption("Ideal para constância e menor risco de perda muscular.")
        elif ritmo == "Moderado (equilíbrio)":
            st.caption("O caminho mais sustentável para a maioria das pessoas.")
        else:
            st.caption("Exige mais foco e disciplina — resultados mais rápidos, mas atenção ao descanso e nutrição.")

    # === STEP 6 — Obstáculos ===
    if step == 6:
        st.subheader("💬 O que mais te impede de chegar no resultado hoje?")
        st.caption(
            "Escolha o que mais se identifica — isso ajuda o calorIA a ajustar lembretes e estratégias certas pra você."
        )

        obstaculos = st.multiselect(
            "Selecione um ou mais:",
            [
                "Rotina corrida / Falta de tempo",
                "Falta de consistência",
                "Falta de motivação",
                "Falta de ideias de refeição",
                "Hábitos alimentares ruins",
                "Compulsão ou ansiedade alimentar",
                "Sono ruim / estresse elevado",
                "Outro (vou explicar abaixo)",
            ],
            default=[],
        )

        outro_obs = st.text_area(
            "Quer detalhar um pouco mais? (opcional)",
            placeholder="Ex: trabalho até tarde e acabo comendo o que tiver...",
            height=70,
        )

        # Salva no estado (padronizado em ob_obs)
        st.session_state.ob_obs = ", ".join(obstaculos) + (f" | {outro_obs.strip()}" if outro_obs.strip() else "")

        st.info("🧠 O calorIA usa isso pra ajustar seu plano de forma mais humana e realista.")

    # === STEP 7 — Estilo de alimentação ===
    if step == 7:
        st.subheader("🥗 Você segue ou gostaria de seguir algum estilo de alimentação?")
        st.caption("Selecione o tipo de alimentação que mais combina com você:")

        dieta = st.radio(
            "",
            [
                "Equilibrada (tradicional, variada)",
                "Low carb",
                "Mediterrânea",
                "Vegana ou vegetariana",
                "Jejum intermitente",
                "Outro estilo / indeciso",
            ],
            index=0,
        )

        st.session_state.dieta = dieta
        st.info("✨ Essa informação será usada para adaptar sugestões de refeições, cardápios e lembretes personalizados.")

    # === STEP 8 — Saúde e objetivos secundários ===
    if step == 8:
        st.subheader("❤️ Sobre sua saúde e bem-estar")

        condicoes = st.multiselect(
            "Você tem alguma dessas condições de saúde?",
            ["Diabetes", "Colesterol alto", "Hipertensão", "Tireoide / hormonal", "Nenhuma dessas"],
            default=[],
        )
        st.session_state.condicoes = ", ".join(condicoes)

        st.markdown("---")

        st.subheader("🎯 Além do peso, o que mais você busca?")
        objetivos_sec = st.multiselect(
            "Escolha o que também é importante pra você:",
            [
                "Mais energia e disposição",
                "Melhorar autoestima",
                "Dormir melhor",
                "Reduzir ansiedade / compulsão",
                "Criar hábitos consistentes",
                "Ganhar força / performance",
            ],
            default=[],
        )
        st.session_state.objetivos_sec = ", ".join(objetivos_sec)

        st.info("Esses dados ajudam o calorIA a priorizar os lembretes, desafios e sugestões de rotina que mais combinam com você.")

    # === STEP 9 — Pronto para começar ===
    if step == 9:
        st.markdown("## 🌱 Você está pronto pra começar")
        st.markdown(
            "Você tem **potencial real** pra transformar seu corpo e sua rotina.\n\n"
            "Em **30 dias**, já dá pra sentir a diferença: mais leveza, energia e progresso visível.\n\n"
            "O **calorIA** simplifica o processo e te ajuda a manter a **constância** — sem radicalismos."
        )

        import numpy as np
        semanas = list(range(1, 13))
        peso = np.linspace(100, 85, len(semanas))  # Exemplo simbólico: redução de peso
        df = pd.DataFrame({"Semana": semanas, "Peso (kg)": peso})

        st.line_chart(df, x="Semana", y="Peso (kg)", use_container_width=True)
        st.caption("📉 Exemplo simbólico: redução média de peso em 12 semanas com constância.")

        st.info("Quase lá! Clique em **Próximo →** para finalizar suas permissões e liberar o app.")

    # === STEP 10 — Permissões ===
    if step == 10:
        st.subheader("🔔 Permissões e lembretes")
        st.caption("Quer que o calorIA te lembre de manter o foco?")

        st.markdown("### 📆 Lembrete semanal de check-in")
        notify_checkin = st.toggle("Ativar lembrete semanal de progresso", value=True)
        st.caption("Receba um lembrete para registrar peso e evolução uma vez por semana.")

        st.markdown("### 💧 Notificações diárias (opcional)")
        notify_daily = st.toggle("Ativar lembretes diários de água e refeições", value=False)
        st.caption("Lembretes de hidratação e refeições para te ajudar na constância.")

        st.session_state.notify_checkin = notify_checkin
        st.session_state.notify_daily = notify_daily

        st.markdown("---")
        st.info("Essas permissões são opcionais. Você pode ativar ou desativar a qualquer momento nas configurações do app.")

    # === STEP 11 — Avalie o app & Depoimentos ===
    if step == 11:
        st.subheader("⭐ Curtiu até aqui? Ajude com 1 toque!")
        st.caption("Sua avaliação ajuda outras pessoas a conhecerem o calorIA e dá gás pra gente continuar melhorando.")

        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("#### iOS / Apple Store")
            st.link_button("Avaliar no iOS", "https://apps.apple.com/", use_container_width=True)
            st.caption("Abra pelo iPhone para ir direto à App Store.")
        with col_b:
            st.markdown("#### Android / Google Play")
            st.link_button("Avaliar no Android", "https://play.google.com/store", use_container_width=True)
            st.caption("Abra pelo Android para ir direto à Play Store.")

        st.divider()
        st.subheader("💬 O que a galera está dizendo")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**Fernanda S. (-6,8 kg em 7 semanas)**\n\n'Pela primeira vez entendi quanto comer sem pirar. Os lembretes e o scanner salvaram minha rotina!'")
        with c2:
            st.markdown("**Rafael M. (definição + mais energia)**\n\n'Só de registrar e seguir as calorias alvo, meu shape já mudou. O check-in semanal mantém no trilho.'")
        with c3:
            st.markdown("**Carla A. (fim do efeito sanfona)**\n\n'A diferença foi a constância. O app é simples, e as metas são realistas.'")

    # === STEP 12 — Resumo personalizado antes de liberar ===
    if step == 12:
        st.subheader("📌 Seu resumo personalizado")
        goal_norm = _normalize_goal(goal)

        # Recalcula para garantir consistência
        idade = _idade_from_dob(dob or date(1995, 1, 1))
        bmr = _bmr_mifflin(weight_kg, height_cm, idade, sex)
        tdee_val = _tdee(weight_kg, height_cm, idade, sex, atividade)
        ajuste = {"Emagrecer": -20, "Ganhar massa": 15, "Manutenção": 0}[goal_norm]
        kcal_alvo = tdee_val * (1 + ajuste/100.0)

        # Macros sugeridos por objetivo (padrões simples e editáveis depois)
        splits = {
            "Emagrecer": {"P": 0.30, "C": 0.40, "G": 0.30},
            "Ganhar massa": {"P": 0.25, "C": 0.50, "G": 0.25},
            "Manutenção": {"P": 0.25, "C": 0.45, "G": 0.30},
        }
        s = splits[goal_norm]
        prot_kcal = kcal_alvo * s["P"]
        carb_kcal = kcal_alvo * s["C"]
        gord_kcal = kcal_alvo * s["G"]
        prot_g = round(prot_kcal / 4)
        carb_g = round(carb_kcal / 4)
        gord_g = round(gord_kcal / 9)

        # Projeção de data para atingir meta
        semanas = _semanas_para_alvo(weight_kg, target_weight_kg, goal_norm)
        from datetime import timedelta
        data_meta_txt = "—"
        if semanas > 0:
            data_meta = date.today() + timedelta(weeks=semanas)
            data_meta_txt = data_meta.strftime("%d/%m/%Y")

        c1, c2, c3 = st.columns(3)
        c1.metric("🔥 BMR", f"{bmr:,.0f} kcal/d")
        c2.metric("⚙️ TDEE", f"{tdee_val:,.0f} kcal/d")
        c3.metric("🎯 Calorias alvo", f"{kcal_alvo:,.0f} kcal/d")

        st.caption("Você pode **editar isso a qualquer momento** em Configurações → Metas.")

        st.markdown("### 🍽️ Macros sugeridos (editáveis)")
        colp, colc, colg = st.columns(3)
        colp.metric("Proteínas", f"{prot_g} g/d")
        colc.metric("Carboidratos", f"{carb_g} g/d")
        colg.metric("Gorduras", f"{gord_g} g/d")

        st.markdown("### 🗓️ Projeção")
        if semanas > 0:
            delta = abs(weight_kg - target_weight_kg)
            st.info(f"⏳ Em ~{semanas} semanas (≈ {data_meta_txt}) você pode ajustar ~{delta:.1f} kg mantendo constância.")
        else:
            st.info("Você já está muito perto da meta — foco em manter e evoluir a performance.")

        st.markdown("### 🛠️ Como atingir seu objetivo")
        tips = [
            "Registre suas refeições diariamente (mesmo as ‘fora da linha’).",
            "Siga a recomendação de calorias alvo com margem de ±5%.",
            "Beba água: ~35 ml/kg ao dia.",
            "Faça o check‑in semanal (peso/foto) — constância > perfeição.",
            "Use o scanner de IA para agilizar o registro.",
            "Durma bem: 7–9h melhora saciedade e recuperação.",
        ]
        for t in tips:
            st.markdown(f"- {t}")

        st.caption("Dica: quer ajustar o plano agora? Clique em **Voltar** para editar objetivo/peso meta.")

    # === STEP 13 — Paywall: PRO Mensal vs Anual + FREE sutil ===
    if step == 13:
        _sp, _x = st.columns([0.9, 0.1])
        with _x:
            if st.button("✕", key="btn_close_paywall", help="Continuar no plano FREE"):
                # Agora o X FINALIZA na hora (salva + redireciona)
                _save_onboarding_and_go_home()

        st.caption("✨ Último passo antes de liberar seu painel!")
        st.markdown("## 💎 Desbloqueie seu plano completo")

        st.markdown("### 🔥 Benefícios do PRO")
        beneficios_pro = [
            "🤖 Scanner de calorias com IA ilimitado",
            "🍱 Planos alimentares completos e substituições",
            "📊 Relatórios avançados de evolução",
            "🧠 Insights e recomendações personalizadas",
            "🥗 Receitas exclusivas e ilimitadas",
            "🏅 Sistema de metas e gamificação",
        ]
        for b in beneficios_pro:
            st.markdown(f"- {b}")

        st.divider()
        st.markdown("### Escolha seu plano")

        # preços (ajuste aqui)
        preco_mensal = "R$ 29,90/mês"
        preco_anual  = "R$ 239,00/ano"
        economia_txt = "Economize ~33% no anual"

        col_m, col_a = st.columns(2)
        with col_m:
            st.markdown("#### PRO Mensal")
            st.markdown(f"**{preco_mensal}**")
            st.caption("3 dias grátis • Cancele quando quiser")
            if st.button("Começar no PRO Mensal", use_container_width=True, key="btn_pro_mensal"):
                # aqui normalmente você chamaria o checkout (Stripe/etc.)
                # por enquanto, apenas marca e finaliza igual ao FREE
                st.session_state.plano_escolhido = "PRO_M"
                _save_onboarding_and_go_home()

        with col_a:
            st.markdown("#### PRO Anual")
            st.markdown(f"**{preco_anual}**")
            st.caption(f"{economia_txt} • 3 dias grátis")
            if st.button("Começar no PRO Anual", use_container_width=True, key="btn_pro_anual"):
                st.session_state.plano_escolhido = "PRO_A"
                _save_onboarding_and_go_home()

    # === Navegação global (fora dos steps) — DENTRO da função render_onboarding ===
    st.divider()
    show_prev = (step > 1) and (step != 13)  # sem voltar no paywall
    show_next = (step < 13)                  # até antes do paywall

    col_prev, col_next = st.columns(2)

    with col_prev:
        if show_prev and st.button("← Voltar", key="btn_voltar"):
            st.session_state.ob_step -= 1
            st.rerun()

    with col_next:
        # Regras de travamento de "Próximo"
        can_go_next = True
        if step == 1 and not _is_authed():
            can_go_next = False
            st.caption("⚠️ Crie sua conta ou faça login para continuar.")

        if step == 3:
            missing = []
            if not str(full_name).strip():
                missing.append("Nome completo")
            try:
                if not (120 <= float(height_cm) <= 230):
                    missing.append("Altura válida")
            except Exception:
                missing.append("Altura válida")
            try:
                if not (30 <= float(weight_kg) <= 300):
                    missing.append("Peso válido")
            except Exception:
                missing.append("Peso válido")
            if not atividade:
                missing.append("Nível de atividade")
            if missing:
                can_go_next = False
                st.caption("⚠️ Preencha os campos: " + ", ".join(missing))

        if show_next:
            if st.button("Próximo →", key="btn_proximo", disabled=not can_go_next):
                # salva parciais no estado
                st.session_state.ob_name = full_name
                st.session_state.ob_dob = dob
                st.session_state.ob_sex = sex
                st.session_state.ob_h = height_cm
                st.session_state.ob_w = weight_kg
                st.session_state.ob_act = atividade
                st.session_state.ob_goal = goal
                st.session_state.ob_target = target_weight_kg
                st.session_state.ob_obs = obstacles
                st.session_state.ob_step += 1
                st.rerun()

        elif step >= 14:
            # "Concluir" com guard de sessão válida (RLS)
            if st.button("Concluir ✅", key="btn_concluir"):
                auid = _auth_uid_or_none()
                if not auid or str(auid) != str(uid):
                    st.warning("Sua sessão expirou. Faça login para concluir.")
                    st.session_state.ob_step = 1
                    st.session_state.auth_mode = "login"
                    st.rerun()

                try:
                    goal_to_save = _normalize_goal(goal)

                    # update do perfil (RLS: id = auth.uid())
                    supabase.table("profiles").update(
                        {
                            "full_name": full_name or None,
                            "dob": str(dob) if dob else None,
                            "sex": sex,
                            "height_cm": float(height_cm) if height_cm else None,
                            "weight_kg": float(weight_kg) if weight_kg else None,
                            "goal": goal_to_save,
                            "target_weight_kg": float(target_weight_kg) if target_weight_kg else None,
                            "obstacles": (st.session_state.get("ob_obs") or "").strip() or None,
                            "onboarding_done": True,
                        }
                    ).eq("id", uid).execute()

                    # weight_logs: insere HOJE só se ainda não existir
                    today_str = str(date.today())
                    exists = supabase.table("weight_logs") \
                        .select("id") \
                        .eq("user_id", uid) \
                        .eq("ref_date", today_str) \
                        .limit(1) \
                        .execute()
                    if not getattr(exists, "data", exists):
                        supabase.table("weight_logs").insert({
                            "user_id": uid,           # RLS: with check (user_id = auth.uid())
                            "ref_date": today_str,
                            "weight_kg": float(weight_kg),
                        }).execute()

                    # terminou → ir para o painel
                    st.success("Onboarding concluído! Redirecionando…")
                    st.session_state.onboarding_done = True
                    # se usa multipage:
                    # st.switch_page("pages/01_Diario_Alimentar.py")
                    # ou roteador simples:
                    st.session_state.route = "home"
                    st.rerun()

                except Exception as e:
                    st.error(f"Erro ao salvar: {e}")

