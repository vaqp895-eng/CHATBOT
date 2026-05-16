import os
import logging
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
import time
from datetime import datetime
from collections import deque

from services.memory import (
    memory_store, 
    lock, 
    MAX_MENSAJES,
    obtener_historial,
    iniciar_google
)
 
try:
    from services.tools import iniciar_google, actualizar_sheet
    from services.memory import cambiar_modo, guardar_interaccion
    from routes.webhook import enviar_texto
    IMPORTS_OK = True
except Exception as e:
    print(f"⚠️  Error importando: {e}")
    IMPORTS_OK = False

memory_store = {}

# ===== SETUP LOGGING =====
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
 
# ===== MODELOS =====
class RespuestaInput(BaseModel):
    numero: str = Field(..., min_length=7, max_length=20)
    mensaje: str = Field(..., min_length=1, max_length=4000)
 
class ModoInput(BaseModel):
    numero: str = Field(..., min_length=7, max_length=20)
    # ✅ CORREGIDO: regex → pattern (Pydantic v2)
    modo: str = Field(..., pattern="^(AUTO|HUMANO|CATALOGO)$")
 
# ===== ROUTER =====
router = APIRouter(prefix="/panel", tags=["Panel Asesor"])
 
 
# ===== ENDPOINT: Panel HTML =====
@router.get("/", response_class=HTMLResponse)
async def panel():
    """Retorna la página HTML del panel"""
    try:
        panel_path = os.path.join("templates", "panel.html")
        
        if not os.path.exists(panel_path):
            logger.error(f"❌ Archivo no encontrado: {panel_path}")
            return "<h1>❌ panel.html no encontrado</h1>"
        
        with open(panel_path, "r", encoding="utf-8") as f:
            logger.info("✅ Panel HTML cargado")
            return f.read()

    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return f"<h1>Error: {e}</h1>"
 
 
# ===== ENDPOINT: Health Check =====
@router.get("/health")
async def health():
    """Verifica que el panel funciona"""
    checks = {
        "panel": "✅ Activo",
        "imports": "✅ OK" if IMPORTS_OK else "❌ Error",
        "timestamp": datetime.now().isoformat(),
    }
    
    try:
        sheet = iniciar_google()
        checks["google_sheets"] = "✅ Conectado"
    except Exception as e:
        checks["google_sheets"] = f"❌ Error: {str(e)[:50]}"
    
    logger.info(f"🏥 Health: {checks}")
    return checks
 
 
# ===== ENDPOINT: OBTENER CHATS (Solo Pendiente Asesor) =====
@router.get("/chats")
async def obtener_chats():
    try:
        logger.info("📊 Obteniendo chats pendientes...")
        
        sheet = iniciar_google()
        if not sheet:
            logger.error("❌ Google Sheets no disponible")
            raise HTTPException(status_code=500, detail="Google Sheets no disponible")
        
        # Obtener todos los registros
        data = sheet.get_all_records()
        logger.info(f"✅ {len(data)} registros totales obtenidos")
        
        chats = []
        
        # FILTRAR SOLO "Pendiente Asesor"
        for i, row in enumerate(data):
            try:
                # Verificar que estado sea "Pendiente Asesor"
                estado = str(row.get("Estado", "")).strip()
                
                if estado == "Pendiente Asesor":  
                    chat = {
                        "id": i,
                        "numero": str(row.get("Numero", "?")).strip(),
                        "mensaje": str(row.get("Ultimo Mensaje", "-"))[:60],
                        "modo": str(row.get("Modo", "?")).strip(),
                        "estado": estado,
                        "hora": str(row.get("Hora", "-")).strip(),
                        "empresa": str(row.get("Empresa", "-")).strip(),
                        "servicio": str(row.get("Servicio", "-")).strip(),
                        "intercambios": row.get("Intercambios", 0),
                        "historial_raw": str(row.get("Historial", "")).strip(),
                    }
                    chats.append(chat)
                    logger.info(f"   ✅ Chat agregado: {chat['numero']}")
            
            except Exception as e:
                logger.warning(f"⚠️  Error procesando fila {i}: {e}")
                continue
        
        logger.info(f"✅ {len(chats)} chats PENDIENTES encontrados")
        
        return {
            "status": "ok",
            "count": len(chats),
            "chats": chats,
            "timestamp": datetime.now().isoformat()
        }
    
    except Exception as e:
        logger.error(f"❌ Error en obtener_chats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
 
 
# ===== ENDPOINT: OBTENER NÚMEROS (Para dropdown) =====
@router.get("/numeros")
async def obtener_numeros():
    """
    Obtiene lista de TODOS los números para el dropdown
    """
    try:
        logger.info("📱 Obteniendo lista de números...")
        
        sheet = iniciar_google()
        if not sheet:
            raise HTTPException(status_code=500, detail="Google Sheets no disponible")
        
        data = sheet.get_all_records()
        
        numeros = []
        for row in data:
            numero = str(row.get("Numero", "")).strip()
            if numero and isinstance(numero, str) and numero != "":
                numeros.append({
                    "numero": numero,
                    "estado": row.get("Estado", "-"),
                    "nombre": f"{numero} - {row.get('Empresa', '-').strip()}"})
        
        # Eliminar duplicados
        numeros_unicos = {n['numero']: n for n in numeros}.values()
        numeros = list(numeros_unicos)
        
        logger.info(f"✅ {len(numeros)} números únicos encontrados")
        return {"status": "ok", "numeros": numeros}
    
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
 
 
# ===== ENDPOINT: OBTENER HISTORIAL =====
@router.get("/chat/{numero}")
async def ver_chat(numero: str):
    """
    Obtiene el historial completo de un usuario
    Parsea la columna "Historial" de Google Sheets
    """
    try:
        logger.info(f"📝 Obteniendo historial de {numero}...")
        historial_memoria = obtener_historial(numero)
        if historial_memoria:
            logger.info(f"   ✅ Encontrado en memory_store: {len(historial_memoria)} mensajes")
        else:
            logger.info(f"   ❌ No encontrado en memory_store, cargando de Sheets...")
        sheet = iniciar_google()
        if not sheet:
            raise HTTPException(status_code=500, detail="Google Sheets no disponible")
        
        data = sheet.get_all_records()
        
        # Buscar el registro con este número
        registro = None
        for row in data:
            if str(row.get("Numero", "")).strip() == str(numero).strip():
                registro = row
                break
        
        if not registro:
            logger.warning(f"⚠️  Usuario no encontrado en Sheets")
            return {
                "numero": numero,
                "historial":historial_memoria or [],
                "count": len(historial_memoria) if historial_memoria else 0,
                "mensaje": "Usuario no encontrado",
                "empresa": "-",
                "servicio": "-",
                "fuente": "memory" if historial_memoria else "ninguna"
            }
        
        # Extraer historial de la columna "Historial"
        historial_sheets_raw = registro.get("Historial", "")
        if historial_sheets_raw:
            logger.info(f"   3️⃣ Sincronizando Sheets → memory_store...")
            historial_sheets = parsear_historial(historial_sheets_raw)
            if not historial_memoria or len(historial_sheets) > len(historial_memoria):
                logger.info(f"      Memory tiene {len(historial_memoria) if historial_memoria else 0}, Sheets tiene {len(historial_sheets)}")
                logger.info(f"      Sincronizando...")
                with lock:
                    if numero not in memory_store:
                        memory_store[numero] = {
                            "historial": deque(maxlen=MAX_MENSAJES),
                            "last_update": time.time(),
                            "modo": "AUTO",
                            "last_mode_check": 0
                        }
                    
                    # Limpiar historial viejo
                    memory_store[numero]["historial"].clear()
                    
                    # Agregar mensajes de Sheets
                    for msg in historial_sheets:
                        memory_store[numero]["historial"].append(msg)
                    
                    memory_store[numero]["last_update"] = time.time()
                historial_memoria = historial_sheets
            else:
                logger.info(f"      Memory ya está actualizado")
        else:
            logger.info(f"   3️⃣ Sheets vacío, usando memory_store")
        historial_final = historial_memoria or []
        fuente = "memory" if historial_memoria else ("sheets" if historial_sheets_raw else "ninguna")

        return {
            "numero": numero,
            "historial": historial_final,
            "count": len(historial_final),
            "mensaje": f"{len(historial_final)} mensajes encontrados",
            "empresa": registro.get("Empresa", "-"),
            "servicio": registro.get("Servicio", "-"),
            "fuente": fuente  # Para debugging
        }
    
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
 
 
# ===== FUNCIÓN: Parsear Historial =====
def parsear_historial(historial_raw: str):
    """
    Parsea el historial desde Google Sheets
    Formato esperado: "Cliente: msg | Bot: msg | Cliente: msg"
    
    Retorna: [{"role": "user", "content": "msg"}, {"role": "assistant", "content": "msg"}]
    """
    if not historial_raw or historial_raw.strip() == "":
        return []
    
    historial = []
    
    # Dividir por "|"
    partes = historial_raw.split("|")
    
    for parte in partes:
        parte = parte.strip()
        if not parte:
            continue
        
        # Buscar "Cliente:" o "Bot:"
        if parte.startswith("Cliente:"):
            contenido = parte.replace("Cliente:", "").strip()
            historial.append({
                "role": "user",
                "content": contenido
            })
        elif parte.startswith("BOT:"):
            contenido = parte.replace("BOT:", "").strip()
            historial.append({
                "role": "assistant",
                "content": contenido
            })
        else:
            historial.append({"role": "user", "content": parte})
    
    return historial
 
 
# ===== ENDPOINT: Responder =====
@router.post("/responder")
async def responder(data: RespuestaInput):
    """
    Envía respuesta al cliente
    """
    numero = data.numero
    mensaje = data.mensaje
    logger.info(f"📨 Respuesta a {numero}")
    
    try:
        # Validar
        if not numero or len(numero) < 7:
            raise ValueError("Número inválido")
        
        if not mensaje or len(mensaje) < 1:
            raise ValueError("Mensaje vacío")
        
        # Enviar por WhatsApp
        logger.info(f"   → Enviando por WhatsApp... ✅ Validación OK")
        sheet = iniciar_google()
        if not sheet:
            raise HTTPException(status_code=500, detail="Google Sheets no disponible")
        data_sheet = sheet.get_all_records()
        fila_existente = None
        registro = None
        for i, row in enumerate(data_sheet):
            if str(row.get("Numero", "")).strip() == str(numero).strip():
                fila_existente = i + 2  
                registro = row
                break
        if not registro:
            logger.error(f"❌ Cliente {numero} no encontrado en Sheets")
            raise ValueError("Cliente no encontrado en la base de datos")
        logger.info(f"   ✅ Cliente encontrado en fila {fila_existente}")

        logger.info(f"   📤 Enviando a WhatsApp...")    
        try:
            await enviar_texto(numero, mensaje)
            logger.info(f"   ✅ WhatsApp OK")
        except Exception as e:
            logger.error(f"   ❌ Error WhatsApp: {e}")
            raise HTTPException(status_code=500, detail=f"Error WhatsApp: {str(e)}")
        logger.info(f"   💾 Guardando en Sheets...")
        try:
            # Guardar en historial
            guardar_interaccion(numero, "assistant", mensaje)
        except Exception as e:
            logger.warning(f"   ⚠️  Error guardando (no es crítico): {e}")
        cambiar_modo(numero, "HUMANO")
        
        logger.info(f"✅ Respuesta enviada a {numero}")
        try:
            cambiar_modo(numero, "HUMANO")
            logger.info(f"   ✅ Modo cambiado")
        except Exception as e:
            logger.warning(f"   ⚠️  Error cambiando modo: {e}")
        return {
            "status": "ok",
            "numero": numero,
            "mensaje": "Respuesta enviada correctamente"
        }
    
    except ValueError as e:
        logger.error(f"❌ Validación: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
 
 
# ===== ENDPOINT: Cambiar Modo =====
@router.post("/modo")
async def cambiar_modo_endpoint(data: ModoInput):
    """Cambia el modo de un usuario"""
    numero = data.numero
    nuevo_modo = data.modo
    
    logger.info(f"🔄 Cambiando modo: {numero} → {nuevo_modo}")
    
    try:
        actualizar_sheet(numero, nuevo_modo)
        cambiar_modo(numero, nuevo_modo)
        logger.info(f"✅ Modo cambiado")
        
        return {
            "status": "ok",
            "numero": numero,
            "modo": nuevo_modo
        }
    
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
 
 
if __name__ == "__main__":
    logger.info("🧪 Testing panel.py")