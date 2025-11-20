# pages/07_Follow_Up.py
import streamlit as st
import pandas as pd
from datetime import datetime, date
from pathlib import Path

st.set_page_config(
    page_title="Check-in Semanal",
    page_icon="📊",
    layout="centered",
    initial_sidebar_state="collapsed"
)

from helpers import (
    apply_theme, supabase,
    storage_public_url, local_img_path,
    add_points, award_badge, salvar_medidas, _show_image
)

apply_theme()

uid = st.session_state.get("user_id")
if not uid:
    st.warning("Faça login para acessar o check-in.")
    st.stop()

st.subheader("Check-in semanal")

session = st.session_state.get("sb_session")
if not session:
    st.info("Faça login para registrar e visualizar seus follow ups.")
else:
    uid = session.user.id

    with st.form("follow_form"):
        col0 = st.columns(2)
        with col0[0]:
            ref_date = st.date_input("Data do check-in", value=datetime.today().date())
            weight_kg = st.number_input(
                "Peso corporal da semana (kg)",
                min_value=30.0,
                max_value=300.0,
                step=0.1,
            )
        with col0[1]:
            st.caption("0 = pior / 10 = excelente")

        # notas 0–10
        c1, c2 = st.columns(2)
        with c1:
            sleep = st.slider("Sono", 0, 10, 7)
            bowel = st.slider("Intestino", 0, 10, 7)
            hunger = st.slider("Fome", 0, 10, 5)
            motivation = st.slider("Motivação", 0, 10, 7)
        with c2:
            stress = st.slider("Estresse", 0, 10, 4)
            anxiety = st.slider("Ansiedade", 0, 10, 4)
            adherence = st.slider("Adesão / Constância", 0, 10, 7)

        st.markdown("**Comentários (opcional)**")
        notes_sleep = st.text_area("Sono — observações", height=70)
        notes_bowel = st.text_area("Intestino — observações", height=70)
        notes_hunger = st.text_area("Fome — observações", height=70)
        notes_motivation = st.text_area("Motivação — observações", height=70)
        notes_stress = st.text_area("Estresse — observações", height=70)
        notes_anxiety = st.text_area("Ansiedade — observações", height=70)
        notes_adherence = st.text_area("Adesão — observações", height=70)

        submitted = st.form_submit_button("Salvar follow up")
        if submitted:
            try:
                payload = {
                    "user_id": uid,
                    "ref_date": str(ref_date),
                    "weight_kg": float(weight_kg) if weight_kg else None,
                    "sleep": sleep,
                    "bowel": bowel,
                    "hunger": hunger,
                    "motivation": motivation,
                    "stress": stress,
                    "anxiety": anxiety,
                    "adherence": adherence,
                    "notes_sleep": notes_sleep.strip() or None,
                    "notes_bowel": notes_bowel.strip() or None,
                    "notes_hunger": notes_hunger.strip() or None,
                    "notes_motivation": notes_motivation.strip() or None,
                    "notes_stress": notes_stress.strip() or None,
                    "notes_anxiety": notes_anxiety.strip() or None,
                    "notes_adherence": notes_adherence.strip() or None,
                }

                supabase.table("followups").insert(payload).execute()
                st.success("Follow up salvo com sucesso!")

                # Pontos + badge
                if add_points(uid, "followup", event_key=str(date.today())):
                    award_badge(uid, "Primeiro follow up concluído")
                    st.toast("🪙 +5 FC ganhos!")
                    st.success("🎖️ Você desbloqueou a missão: Primeiro follow up concluído")

            except Exception as e:
                st.error(f"Erro ao salvar follow up: {e}")

    st.divider()
    st.subheader("Seus últimos follow ups")
    try:
        resp = (
            supabase.table("followups")
            .select("*")
            .eq("user_id", uid)
            .order("ref_date", desc=True)
            .limit(20)
            .execute()
        )

        rows = resp.data or []
        if not rows:
            st.caption("Ainda não há registros.")
        else:
            df = pd.DataFrame(rows)
            cols_order = [
                "ref_date", "weight_kg", "sleep", "bowel", "hunger", "motivation",
                "stress", "anxiety", "adherence",
                "notes_sleep", "notes_bowel", "notes_hunger",
                "notes_motivation", "notes_stress", "notes_anxiety", "notes_adherence",
                "created_at", "id"
            ]
            df = df[[c for c in cols_order if c in df.columns]]
            st.dataframe(df, use_container_width=True)
    except Exception as e:
        st.warning(f"Não foi possível listar: {e}")

    # ===== MEDIDAS =====
    st.divider()
    st.subheader("📏 Medidas corporais")

    with st.expander("Orientações e exemplos", expanded=True):
        st.markdown("**Use fita métrica apertando levemente na pele.**")
        sexo_ref = st.radio("Ver exemplo para:", ["Masculino", "Feminino"], horizontal=True)
        if sexo_ref == "Masculino":
            img = storage_public_url("guides", "measure_male.jpg") or local_img_path("measure_male")
        else:
            img = storage_public_url("guides", "measure_female.jpeg") or local_img_path("measure_female")
        _show_image(img)

    with st.form("measure_form"):
        colA, colB, colC = st.columns(3)
        with colA:
            m_date = st.date_input("Data da medição", value=datetime.today().date())
            chest_cm = st.number_input("Peito/Tórax (cm)", min_value=0.0, step=0.1)
            arm_cm = st.number_input("Braço (cm)", min_value=0.0, step=0.1)
        with colB:
            waist_cm = st.number_input("Cintura (cm)", min_value=0.0, step=0.1)
            abdomen_cm = st.number_input("Abdômen (cm)", min_value=0.0, step=0.1)
            hip_cm = st.number_input("Quadril (cm)", min_value=0.0, step=0.1)
        with colC:
            thigh_cm = st.number_input("Coxa (cm)", min_value=0.0, step=0.1)
            calf_cm = st.number_input("Panturrilha (cm)", min_value=0.0, step=0.1)
            st.caption("Padronize o lado (ex.: sempre o direito).")

        save_meas = st.form_submit_button("💾 Salvar medidas")

    if save_meas:
        medidas_id = salvar_medidas(uid, m_date, chest_cm, arm_cm, waist_cm, abdomen_cm, hip_cm, thigh_cm, calf_cm)
        if medidas_id:
            st.success("Medidas salvas com sucesso!")
            if add_points(uid, "add_measure_photo", event_key=str(medidas_id)):
                award_badge(uid, "Primeira medição registrada")
                st.toast("🪙 +3 FC ganhos!")
                st.success("🎖️ Você desbloqueou a missão: Primeira medição concluída")
        else:
            st.error("Falha ao salvar medidas.")

    # === Listagem medidas ===
    st.markdown("### Suas últimas medidas")
    try:
        resp = (
            supabase.table("measurements")
            .select("*")
            .eq("user_id", uid)
            .order("ref_date", desc=True)
            .limit(12)
            .execute()
        )
        ms = resp.data or []
        if not ms:
            st.caption("Ainda não há medições registradas.")
        else:
            dfm = pd.DataFrame(ms)
            dfm["ref_date"] = pd.to_datetime(dfm["ref_date"]).dt.date
            dfm = dfm.sort_values("ref_date")
            for col in ["chest_cm","arm_cm","waist_cm","abdomen_cm","hip_cm","thigh_cm","calf_cm"]:
                if col in dfm.columns:
                    dfm[f"Δ {col.replace('_cm','')}"] = dfm[col].diff().round(1)
            dfm = dfm.sort_values("ref_date", ascending=False)
            cols_show = [c for c in [
                "ref_date","chest_cm","arm_cm","waist_cm","abdomen_cm","hip_cm","thigh_cm","calf_cm",
                "Δ chest","Δ arm","Δ waist","Δ abdomen","Δ hip","Δ thigh","Δ calf"
            ] if c in dfm.columns]
            st.dataframe(dfm[cols_show], use_container_width=True)
    except Exception as e:
        st.warning(f"Não foi possível listar medidas: {e}")

    # === Fotos de progresso ===
    st.divider()
    st.subheader("📸 Fotos de progresso (1x/mês)")

    with st.expander("Orientações e exemplos"):
        st.markdown("**Tente tirar fotos sempre no mesmo local, com mesma iluminação.**")
        sexo_exemplo = st.radio("Ver exemplo para:", ["Feminino", "Masculino"], horizontal=True)
        if sexo_exemplo == "Feminino":
            img = storage_public_url("guides", "example_female.jpeg") or local_img_path("example_female")
        else:
            img = storage_public_url("guides", "example_male.jpeg") or local_img_path("example_male")
        _show_image(img, caption="Exemplo: frente • perfil • costas")

    files = st.file_uploader("Envie suas fotos (PNG/JPG/JPEG)", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
    if files:
        import datetime as _dt
        for f in files:
            try:
                y_m = _dt.datetime.now().strftime("%Y-%m")
                ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
                path = f"{uid}/{y_m}/{ts}-{f.name}".replace(" ", "_").lower()
                supabase.storage.from_("progress-photos").upload(
                    path=path,
                    file=f,
                    file_options={"contentType": f.type or "image/jpeg", "upsert": False},
                )
                st.success(f"Enviado: {f.name}")
            except Exception as e:
                st.error(f"Falha ao enviar {f.name}: {e}")

    st.markdown("### Suas fotos")
    try:
        root_items = supabase.storage.from_("progress-photos").list(path=uid)
        if not root_items:
            st.caption("Ainda não há fotos enviadas.")
        else:
            for folder in sorted(root_items, key=lambda x: x.get("name", "")):
                month_path = f"{uid}/{folder['name']}"
                month_items = supabase.storage.from_("progress-photos").list(path=month_path) or []
                if not month_items:
                    continue
                st.markdown(f"**{folder['name']}**")
                cols = st.columns(3)
                for i, item in enumerate(sorted(month_items, key=lambda x: x.get("name", ""))):
                    full_path = f"{month_path}/{item['name']}"
                    signed = supabase.storage.from_("progress-photos").create_signed_url(full_path, 3600)
                    url = signed.get("signedURL") or signed.get("signed_url")
                    if url:
                        with cols[i % 3]:
                            _show_image(url)
                            st.caption(item["name"])
    except Exception as e:
        st.warning(f"Não foi possível listar as fotos: {e}")
