import re
from typing import Dict, Optional, Tuple
import pdfplumber

# -----------------------------
# Regex e normalizações
# -----------------------------
RE_DATE = r"\b\d{2}/\d{2}/\d{4}\b"
RE_MES_ANO = r"\b(?:JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)\s*/\s*\d{4}\b"

# Moeda BR (ex: 1.262,22 / 0,60 / 535,25)
RE_MONEY_BR = r"\b\d{1,3}(?:\.\d{3})*,\d{2}\b|\b\d+,\d{2}\b"

# Número BR geral (permite inteiros longos e milhares com ponto):
# - 16774
# - 16.774
# - 5.920,00
# - 0
RE_NUM_BR = r"(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{2})?"

def clean_spaces(s: str) -> str:
    return re.sub(r"[ \t]+", " ", (s or "")).strip()

def normalize_kwh(raw: str) -> Optional[int]:
    """
    kWh: converte para inteiro.
    Aceita:
      "5.920,00" -> 5920
      "16.774"   -> 16774
      "10 504"   -> 10504  (se vier quebrado com espaço)
      "33271"    -> 33271
    """
    if not raw:
        return None
    s = raw.strip().replace(" ", "")
    if "," in s:
        s = s.split(",")[0]
    s = s.replace(".", "")
    s = re.sub(r"\D", "", s)
    return int(s) if s else None

def normalize_brl(raw: str) -> Optional[float]:
    """
    R$: retorna float.
    Ex:
      "R$ 3.914,15" -> 3914.15
      "1.262,22"    -> 1262.22
      "0,60"        -> 0.60
    """
    if not raw:
        return None
    s = raw.replace("R$", "").replace(" ", "").strip()
    s = re.sub(r"[^0-9\.,]", "", s)
    if not s:
        return None
    # remove separador de milhar e troca vírgula por ponto
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


# -----------------------------
# Leituras por fallback
# -----------------------------
def extract_first_date_after(label: str, text_norm: str) -> Optional[str]:
    m = re.search(rf"{label}.*?({RE_DATE})", text_norm, re.IGNORECASE)
    return m.group(1) if m else None

def extract_leituras_por_bloco(text_norm: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Captura padrão: 'DD/MM/AAAA DD/MM/AAAA <n_dias> DD/MM/AAAA'
    onde:
      1º = leitura anterior
      2º = leitura atual
    """
    m = re.search(rf"({RE_DATE})\s+({RE_DATE})\s+\d+\s+({RE_DATE})", text_norm)
    if m:
        return m.group(1), m.group(2)
    return None, None


# -----------------------------
# Nome / Código cliente
# -----------------------------
def extract_customer_name(lines: list[str]) -> Optional[str]:
    for l in lines[:80]:
        up = l.upper()
        if any(x in up for x in ["NEOENERGIA", "NOTA FISCAL", "CHAVE DE ACESSO", "PAGUE COM O PIX"]):
            continue
        if len(l) >= 12 and re.search(r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ]", up):
            return l.strip()
    return lines[0].strip() if lines else None

def extract_customer_code(lines: list[str]) -> Optional[str]:
    # regra estável no seu layout: linha imediatamente anterior ao "B3 COMERCIAL / OUTROS"
    for i, l in enumerate(lines):
        if "B3 COMERCIAL" in l.upper() and i > 0:
            cand = lines[i - 1].strip()
            if re.fullmatch(r"[0-9.\-]+", cand):
                return cand
            break

    # fallback
    joined = " ".join(lines)
    m = re.search(r"\b\d{1,3}(?:\.\d{3})*-\d\b|\b\d{6,9}-\d\b", joined)
    return m.group(0) if m else None


# -----------------------------
# REF MES/ANO / Total / Vencimento
# -----------------------------
def extract_ref_mes_ano(text_norm: str) -> Optional[str]:
    m = re.search(RE_MES_ANO, text_norm, re.IGNORECASE)
    return m.group(0).upper().replace(" ", "") if m else None

def extract_total_a_pagar(text_norm: str) -> Optional[str]:
    m = re.search(r"TOTAL\s+A\s+PAGAR.*?(R\$)?\s*([0-9\.\,]+)", text_norm, re.IGNORECASE)
    return normalize_brl(m.group(2)) if m else None

def extract_vencimento(text_norm: str) -> Optional[str]:
    venc = extract_first_date_after("VENCIMENTO", text_norm)
    if venc:
        return venc
    m = re.search(RE_DATE, text_norm)
    return m.group(0) if m else None


# -----------------------------
# Consumo kWh (corrige 5.920,00 -> 5920)
# -----------------------------
def extract_consumo_kwh(lines: list[str]) -> Optional[int]:
    for l in lines:
        up = l.upper()
        if "ENERGIA ATIVA" in up and "UNICO" in up:
            nums = re.findall(RE_NUM_BR, l)
            if nums:
                return normalize_kwh(nums[-1])
    return None


# -----------------------------
# CUSTO TUSD FIO B (VALOR R$)
# -----------------------------
def extract_custo_tusd_fio_b(full_text: str) -> Optional[str]:
    """
    Captura o VALOR (R$) da linha 'CUSTO TUSD FIO B'.
    Regra:
      - achar a linha que contém 'CUSTO TUSD FIO B'
      - pegar o primeiro número moeda (com vírgula e 2 casas), ex: 1.262,22
      - ignorar QUANT (1) e outros inteiros
    """
    lines = [l.strip() for l in full_text.splitlines() if l.strip()]
    for l in lines:
        if "CUSTO TUSD FIO B" in l.upper():
            m = re.search(RE_MONEY_BR, l)
            if m:
                return normalize_brl(m.group(0))

    # fallback: procura perto do label no texto normalizado
    text_norm = clean_spaces(full_text)
    m2 = re.search(r"CUSTO\s+TUSD\s+FIO\s+B.{0,220}?(" + RE_MONEY_BR + r")", text_norm, re.IGNORECASE)
    return normalize_brl(m2.group(1)) if m2 else None


# -----------------------------
# Saldos GD (sem concatenação e sem cortar dígitos)
# -----------------------------
def extract_kwh_after_label(full_text: str, label: str) -> Optional[int]:
    """
    Captura o PRIMEIRO número após o label, evitando:
    - concatenação de números (ex: 332712103553...)
    - corte (ex: 16774 virar 167)
    Também tolera números quebrados com espaço (10 504).
    """
    m = re.search(rf"{label}\s*[:.]*\s*([0-9][0-9\.\,\s]*)", full_text, re.IGNORECASE)
    if not m:
        return None

    tail = m.group(1)
    tail_no_spaces = tail.replace(" ", "")

    m2 = re.search(RE_NUM_BR, tail_no_spaces)
    if not m2:
        return None

    return normalize_kwh(m2.group(0))


# -----------------------------
# Principal
# -----------------------------
def extract_fields_from_pdf(pdf_path: str) -> Dict[str, Optional[str]]:
    full_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            full_text += "\n" + (page.extract_text() or "")

    text_norm = clean_spaces(full_text)
    lines = [l.strip() for l in full_text.splitlines() if l.strip()]

    nome = extract_customer_name(lines)
    codigo = extract_customer_code(lines)

    ref_mes_ano = extract_ref_mes_ano(text_norm)
    total_a_pagar = extract_total_a_pagar(text_norm)
    vencimento = extract_vencimento(text_norm)

    # Leituras
    leitura_anterior = extract_first_date_after("LEITURA ANTERIOR", text_norm)
    leitura_atual = extract_first_date_after("LEITURA ATUAL", text_norm)
    if not leitura_anterior or not leitura_atual:
        la_fb, lat_fb = extract_leituras_por_bloco(text_norm)
        leitura_anterior = leitura_anterior or la_fb
        leitura_atual = leitura_atual or lat_fb

    # CUSTO TUSD FIO B (VALOR R$)
    custo_tusd_fio_b = extract_custo_tusd_fio_b(full_text)

    # Consumo
    consumo = extract_consumo_kwh(lines)

    # Saldos GD
    saldo_anterior = extract_kwh_after_label(full_text, "SALDO ANTERIOR")
    injetado = extract_kwh_after_label(full_text, "INJETADO")
    compensado = extract_kwh_after_label(full_text, "COMPENSADO")
    saldo_atual = extract_kwh_after_label(full_text, "SALDO ATUAL")

    # Se não existir bloco GD, zera
    if saldo_anterior is None and injetado is None and compensado is None and saldo_atual is None:
        saldo_anterior, injetado, compensado, saldo_atual = 0, 0, 0, 0

    return {
        "NOME CLIENTE": nome,
        "CODIGO DO CLIENTE": codigo,
        "REF: MES/ANO": ref_mes_ano,
        "TOTAL A PAGAR (R$)": total_a_pagar,          # ex: "3914.15"
        "VENCIMENTO": vencimento,                     # ex: "03/01/2025"
        "LEITURA ANTERIOR": leitura_anterior,         # ex: "05/11/2025"
        "LEITURA ATUAL": leitura_atual,               # ex: "08/12/2025"
        "CUSTO TUSD FIO B (R$)": custo_tusd_fio_b,     # ex: "1262.22"
        "CONSUMO (kWh)": consumo,                     # int
        "SALDO ANTERIOR (kWh)": saldo_anterior,        # int
        "INJETADO (kWh)": injetado,                    # int
        "COMPENSADO (kWh)": compensado,                # int
        "SALDO ATUAL (kWh)": saldo_atual,              # int
    }

