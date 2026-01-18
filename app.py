import os
import hmac
import io
import tempfile
from pathlib import Path

import streamlit as st
import pandas as pd

from extractor import extract_fields_from_pdf


# -----------------------------
# LOGIN (1 email/senha para todos)
# -----------------------------
def require_login():
    st.session_state.setdefault("logged_in", False)

    if st.session_state["logged_in"]:
        return

    st.title("Login - Extrator de Faturas")

    email = st.text_input("E-mail", placeholder="seu@email.com")
    password = st.text_input("Senha", type="password")

    allowed_email = os.environ.get("APP_LOGIN_EMAIL", "")
    allowed_password = os.environ.get("APP_LOGIN_PASSWORD", "")

    if not allowed_email or not allowed_password:
        st.warning(
            "Admin: credenciais não configuradas neste computador.\n\n"
            "No Terminal, defina:\n"
            'export APP_LOGIN_EMAIL="..." \n'
            'export APP_LOGIN_PASSWORD="..."'
        )

    if st.button("Entrar"):
        email_ok = hmac.compare_digest(email.strip().lower(), allowed_email.strip().lower())
        pass_ok = hmac.compare_digest(password, allowed_password)

        if email_ok and pass_ok:
            st.session_state["logged_in"] = True
            st.rerun()
        else:
            st.error("Credenciais inválidas.")


def logout_button():
    col1, _ = st.columns([1, 5])
    with col1:
        if st.button("Sair"):
            st.session_state["logged_in"] = False
            st.rerun()


# Exige login
require_login()
if not st.session_state.get("logged_in", False):
    st.stop()


# -----------------------------
# APP
# -----------------------------
st.set_page_config(page_title="Extrator de Faturas", layout="wide")

OUTPUT_DIR = Path.home() / "Downloads" / "FaturaExtractor" / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

st.title("Extrator de Faturas - Upload em Lote")
st.caption("Protegido por login. Exporta CSV/Excel e valida saldo.")
logout_button()

uploaded_files = st.file_uploader(
    "Selecione 1 ou mais PDFs",
    type=["pdf"],
    accept_multiple_files=True
)

if uploaded_files:
    rows = []

    for uf in uploaded_files:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(uf.read())
            tmp_path = tmp.name

        fields = extract_fields_from_pdf(tmp_path)
        fields["ARQUIVO"] = uf.name

        # Validação: SALDO ATUAL = SALDO ANTERIOR + INJETADO - COMPENSADO
        try:
            sa = int(fields.get("SALDO ANTERIOR (kWh)") or 0)
            inj = int(fields.get("INJETADO (kWh)") or 0)
            comp = int(fields.get("COMPENSADO (kWh)") or 0)
            calc = sa + inj - comp
            atual = int(fields.get("SALDO ATUAL (kWh)") or 0)

            fields["SALDO ATUAL (CALC)"] = calc
            fields["CHECK SALDO"] = "OK" if atual == calc else "DIVERGENTE"
            fields["DIF (kWh)"] = atual - calc
        except:
            fields["SALDO ATUAL (CALC)"] = None
            fields["CHECK SALDO"] = "ERRO"
            fields["DIF (kWh)"] = None

        # TARIFA FIO B = CUSTO TUSD FIO B (R$) / COMPENSADO (kWh)
        try:
            custo_fio_b = fields.get("CUSTO TUSD FIO B (R$)")
            compensado_kwh = fields.get("COMPENSADO (kWh)")

            if custo_fio_b is None or compensado_kwh in (None, 0):
                fields["TARIFA FIO B (R$/kWh)"] = None
            else:
                fields["TARIFA FIO B (R$/kWh)"] = float(custo_fio_b) / float(compensado_kwh)
        except:
            fields["TARIFA FIO B (R$/kWh)"] = None

        rows.append(fields)

    df = pd.DataFrame(rows)

    ordered_cols = [
        "NOME CLIENTE",
        "CODIGO DO CLIENTE",
        "REF: MES/ANO",
        "TOTAL A PAGAR (R$)",
        "VENCIMENTO",
        "LEITURA ANTERIOR",
        "LEITURA ATUAL",
        "CUSTO TUSD FIO B (R$)",
        "TARIFA FIO B (R$/kWh)",
        "CONSUMO (kWh)",
        "SALDO ANTERIOR (kWh)",
        "INJETADO (kWh)",
        "COMPENSADO (kWh)",
        "SALDO ATUAL (kWh)",
        "SALDO ATUAL (CALC)",
        "CHECK SALDO",
        "DIF (kWh)",
        "ARQUIVO",
    ]
    ordered_cols = [c for c in ordered_cols if c in df.columns]
    df = df[ordered_cols]

    st.subheader("Prévia dos dados extraídos")
    st.dataframe(df, use_container_width=True)

    st.subheader("Exportar")

    csv_data = df.to_csv(index=False, sep=";").encode("utf-8")
    st.download_button(
        "Baixar CSV (;)",
        data=csv_data,
        file_name="extracao_faturas.csv",
        mime="text/csv"
    )

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Extracao")

    st.download_button(
        "Baixar Excel (.xlsx)",
        data=output.getvalue(),
        file_name="extracao_faturas.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # Salva localmente (no Mac)
    excel_path = OUTPUT_DIR / "extracao_faturas.xlsx"
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Extracao")

    st.success(f"Excel salvo automaticamente em: {excel_path}")
else:
    st.info("Faça upload de PDFs para iniciar.")

