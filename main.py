# versão pronta para GitHub + Railway
# Bot Bollinger + Binance
# Funciona localmente envia Telegram / cria ordens / TP1 TP2 e SL
# MOEDAS ERRO COM VALOR INFERIOR (5$) CKB, COTI, ONE, ZIL, JASMY, CHZ,  

# MOEDAS PARA TESTAR: "COWUSDT", "GALAUSDT", "GTCUSDT", "ENAUSDT", "BELUSDT", "IOUSDT"

# proximas melhorias:
# github + railway
# tralling stop

import os
import time
import requests
import numpy as np
from datetime import datetime
from dotenv import load_dotenv
from decimal import Decimal, ROUND_DOWN
import math

load_dotenv()

# =========================
# CONFIGURAÇÕES
# =========================
SYMBOLS = ["1INCHUSDT", "ALGOUSDT", "ARPAUSDT", "DOGEUSDT", "DYDXUSDT", "HUSDT", "SANDUSDT", "STORJUSDT"]
INTERVAL = "1m"

BOLL_PERIOD = 8
BOLL_STD = 2

LOOP_SLEEP = 20

# =========================
# RISK / PROFIT CONFIG
# =========================
QTY = 100  # moedas
LEVERAGE = 10

TP1_PROFIT_PCT = 50    # lucro em %
TP2_PROFIT_PCT = 100   # lucro em %
SL_LOSS_PCT   = 50     # perda em %

last_signal = {s: None for s in SYMBOLS}

# =========================
# BINANCE CLIENTE (sob demanda - para web)
# =========================
from binance.client import Client
from binance.enums import *

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")

if not BINANCE_API_KEY or not BINANCE_API_SECRET:
    raise RuntimeError("BINANCE_API_KEY ou BINANCE_API_SECRET ausentes")

def get_binance_client():
    return Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET, testnet=False)

# =========================
# DATA/HORA
# =========================
def agora_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# =========================
# TELEGRAM
# =========================
def _get_env():
    return os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")

def send_telegram(msg: str):
    token, chat_id = _get_env()
    if not token or not chat_id:
        return  # variáveis ausentes, não envia

    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg},
            timeout=10
        )
    except Exception as e:
        print("[ERRO TELEGRAM]", e)

# =========================
# BOLLINGER
# =========================
def bollinger(closes):
    arr = np.array(closes)
    sma = arr[-BOLL_PERIOD:].mean()
    std = arr[-BOLL_PERIOD:].std()
    upper = sma + BOLL_STD * std
    lower = sma - BOLL_STD * std
    return upper, lower

# ===============================================
# FUNÇÕES DE NORMALIZAÇÃO (PRICE + QTY) + FUNÇÕES AUXILIARES BINANCE
# ===============================================
_exchange_info_cache = None

def get_exchange_info():
    global _exchange_info_cache
    if _exchange_info_cache is None:
        _exchange_info_cache = client.futures_exchange_info()
    return _exchange_info_cache


_symbol_filters_cache = {}

def get_symbol_filters(symbol):
    if symbol in _symbol_filters_cache:
        return _symbol_filters_cache[symbol]

    info = client.futures_exchange_info()

    for s in info["symbols"]:
        if s["symbol"] == symbol:
            filters = {}
            for f in s["filters"]:
                filters[f["filterType"]] = f
            _symbol_filters_cache[symbol] = filters
            return filters

    raise Exception(f"Filtros não encontrados para {symbol}")

def adjust_price(symbol, price):
    filters = get_symbol_filters(symbol)
    tick_size = Decimal(filters["PRICE_FILTER"]["tickSize"])
    price = Decimal(str(price))
    return float((price // tick_size) * tick_size)

def adjust_qty(symbol, qty):
    filters = get_symbol_filters(symbol)
    step_size = Decimal(filters["LOT_SIZE"]["stepSize"])
    qty = Decimal(str(qty))
    return float((qty // step_size) * step_size)

def get_tick_size(symbol):
    info = get_exchange_info()
    for s in info["symbols"]:
        if s["symbol"] == symbol:
            for f in s["filters"]:
                if f["filterType"] == "PRICE_FILTER":
                    return float(f["tickSize"])
    raise Exception(f"tickSize não encontrado para {symbol}")

def get_tick_size(symbol):
    info = get_exchange_info()
    for s in info["symbols"]:
        if s["symbol"] == symbol:
            for f in s["filters"]:
                if f["filterType"] == "PRICE_FILTER":
                    return float(f["tickSize"])
    raise Exception(f"tickSize não encontrado para {symbol}")

def get_step_size(symbol):
    info = get_exchange_info()
    for s in info["symbols"]:
        if s["symbol"] == symbol:
            for f in s["filters"]:
                if f["filterType"] == "LOT_SIZE":
                    return float(f["stepSize"])
    raise Exception(f"stepSize não encontrado para {symbol}")

# =========================
# VERIFICAR SE JÁ EXISTE POSIÇÃO NO LADO
# =========================
def has_open_position(symbol, side):
    positions = client.futures_position_information(symbol=symbol)
    for p in positions:
        if p["positionSide"] == side and float(p["positionAmt"]) != 0:
            return True
    return False
# =========================
# DEFINIR ALAVANCAGEM
# =========================
def set_leverage(symbol):
    try:
        client.futures_change_leverage(
            symbol=symbol,
            leverage=LEVERAGE
        )
    except Exception as e:
        print(f"[{symbol}] ⚠ Falha ao definir alavancagem: {e}")

# =========================
# CRIAR ORDEM DE ENTRADA (MARKET)
# =========================
def open_position(symbol, signal):
    side = SIDE_BUY if signal == "LONG" else SIDE_SELL
    position_side = "LONG" if signal == "LONG" else "SHORT"

    if has_open_position(symbol, position_side):
        print(f"[{symbol}] Já existe posição {position_side}")
        return False

    try:
        set_leverage(symbol)

        step = get_step_size(symbol)
        qty_norm = normalize_qty(QTY, step)

        if qty_norm <= 0:
            raise Exception("Quantidade normalizada inválida")

        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            positionSide=position_side,
            type=ORDER_TYPE_MARKET,
            quantity=qty_norm
        )

        if not order or "orderId" not in order:
            print(f"[{symbol}] Ordem não confirmada pela Binance")
            return False

        print(f"[{symbol}] ✅ Entrada {signal} criada | orderId={order['orderId']}")
        return True

    except Exception as e:
        print(f"[{symbol}] ❌ Falha ao abrir posição: {e}")
        return False

# =========================
# TP E SL (BASEADOS NO PREÇO MÉDIO)
# =========================
def create_tp_sl(symbol, signal):
    position_side = "LONG" if signal == "LONG" else "SHORT"
    side_close = SIDE_SELL if signal == "LONG" else SIDE_BUY
    is_long = signal == "LONG"

    try:
        pos = client.futures_position_information(symbol=symbol)
    except Exception as e:
        print(f"[{symbol}] ❌ Erro ao consultar posição: {e}")
        return False

    entry_price = None
    position_amt = 0

    for p in pos:
        if p["positionSide"] == position_side and float(p["positionAmt"]) != 0:
            entry_price = float(p["entryPrice"])
            position_amt = abs(float(p["positionAmt"]))
            break

    if not entry_price or position_amt <= 0:
        print(f"[{symbol}] ⚠ Nenhuma posição ativa para TP/SL")
        return False

    tick = get_tick_size(symbol)
    step = get_step_size(symbol)

    qty_norm = normalize_qty(position_amt, step)
    half_qty = normalize_qty(qty_norm / 2, step)

    if half_qty <= 0:
        print(f"[{symbol}] ❌ Quantidade insuficiente para TP parcial")
        return False

    # ===== PREÇOS BASE =====
    tp1_price = entry_price * pct_to_price_factor(TP1_PROFIT_PCT, LEVERAGE, is_long)
    tp2_price = entry_price * pct_to_price_factor(TP2_PROFIT_PCT, LEVERAGE, is_long)
    sl_price  = entry_price * pct_to_price_factor(-SL_LOSS_PCT, LEVERAGE, is_long)

    # ===== AJUSTE DE PREÇO BINANCE =====
    tp1_price_adj = adjust_price(symbol, tp1_price)
    tp2_price_adj = adjust_price(symbol, tp2_price)
    sl_price_adj  = adjust_price(symbol, sl_price)

    # ===== AJUSTE DE QUANTIDADE =====
    qty_tp1 = adjust_qty(symbol, half_qty)
    qty_tp2 = adjust_qty(symbol, QTY - half_qty)

    # ===== BLINDAGEM CRÍTICA =====
    if qty_tp1 <= 0 or qty_tp2 <= 0:
       raise Exception("Quantidade ajustada ficou zero")

    try:
        # 🎯 TP1
        client.futures_create_order(
            symbol=symbol,
            side=side_close,
            positionSide=position_side,
            type=ORDER_TYPE_LIMIT,
            quantity=half_qty,
            price=tp1_price_adj,
            timeInForce=TIME_IN_FORCE_GTC,
        )

        # 🎯 TP2
        client.futures_create_order(
            symbol=symbol,
            side=side_close,
            positionSide=position_side,
            type=ORDER_TYPE_LIMIT,
            quantity=qty_norm - half_qty,
            price=tp2_price_adj,
            timeInForce=TIME_IN_FORCE_GTC,
        )

        # 🛑 SL
        client.futures_create_order(
            symbol=symbol,
            side=side_close,
            positionSide=position_side,
            type="STOP_MARKET",
            stopPrice=sl_price_adj,
            closePosition=True,
            workingType="MARK_PRICE"
        )

        print(f"[{symbol}] 🎯 TP1 / TP2 / 🛑 SL criados com sucesso")
        return True

    except Exception as e:
        print(f"[{symbol}] ❌ Erro ao criar TP/SL: {e}")
        return False

# =================================
# FUNÇÃO FINAL: PROCESSAR SINAL
# =================================
def process_signal(symbol, signal):
    if last_signal.get(symbol) == signal:
        print(f"[{symbol}] Sinal repetido ignorado")
        return False

    if not open_position(symbol, signal):
        return False

    if not create_tp_sl(symbol, signal):
        return False

    last_signal[symbol] = signal
    return True

# =========================
# FUNÇÃO AUXILIAR (CONVERSÃO CORRETA)
# =========================
def pct_to_price_factor(pct, leverage, is_long):
    """
    Converte % de lucro/perda em fator de preço,
    considerando alavancagem.
    """
    price_move = pct / leverage / 100  # ex: 50% / 10 = 5% preço

    if is_long:
        return 1 + price_move
    else:
        return 1 - price_move

# =========================
# TESTE DE CONEXÃO BINANCE
# =========================
def test_connection():
    try:
        client = get_binance_client()
        print("✅ Conexão Binance OK")
        print("Saldo USDT:", client.futures_account_balance())
        return True
    except Exception as e:
        print("❌ Erro Binance:", e)
        return False

# =========================
# LOOP PRINCIPAL
# =========================
msg = f"[{SYMBOLS}] 🚀 Bot Bollinger Binance iniciado"
print(msg)
send_telegram(msg)

# =========================
# TESTE ANTES DO LOOP
# =========================
if not test_connection():
    raise RuntimeError("Falha na conexão com Binance. Verifique suas chaves.")


while True:
    try:
        for SYMBOL in SYMBOLS:
            klines = get_klines(SYMBOL, INTERVAL)
            closes = [float(k[4]) for k in klines]
            price = closes[-1]

            upper, lower = bollinger(closes)
            ts = agora_str()

            # ===== SHORT =====
            if price > upper:
                label = "SHORT"

                if last_signal[SYMBOL] != label:
                    send_telegram(f"[{SYMBOL}] {label}\nPreço: {price:.8f}")

                    ok = process_signal(SYMBOL, "SHORT")

                    if ok:
                        last_signal[SYMBOL] = label

            # ===== LONG =====
            elif price < lower:
                label = "LONG"

                if last_signal[SYMBOL] != label:
                    send_telegram(f"[{SYMBOL}] {label}\nPreço: {price:.8f}")

                    ok = process_signal(SYMBOL, "LONG")

                    if ok:
                        last_signal[SYMBOL] = label

    except Exception as e:
        print("[ERRO LOOP]", e)

    time.sleep(LOOP_SLEEP)












