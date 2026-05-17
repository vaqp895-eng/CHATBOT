import time
import threading
from collections import deque
from services.tools import buscar_modo_en_sheet, actualizar_sheet
from services.tools import iniciar_google

memory_store = {}
lock = threading.Lock()

EXPIRATION_TIME = 6 * 60 * 60  # 6 horas
MAX_USERS = 1000
MAX_MENSAJES = 10  # cantidad de mensajes por usuario

TTL_AUTO = 120
TTL_HUMANO = 600 

def obtener_modo(numero):
    if numero not in memory_store:
        guardar_interaccion(numero, "user", "")

    with lock:
        data = memory_store[numero]
        ahora = time.time()

        ttl = TTL_AUTO if data["modo"] == "AUTO" else TTL_HUMANO

        if ahora - data["last_mode_check"] < ttl:
            return data["modo"]

    modo_sheet = buscar_modo_en_sheet(numero)

    with lock:
        memory_store[numero]["modo"] = modo_sheet
        memory_store[numero]["last_mode_check"] = time.time()

    return modo_sheet

def cambiar_modo(numero, nuevo_modo):
    print(f"\n🔄 CAMBIAR_MODO iniciado")
    print(f"   📱 Número: {numero}")
    print(f"   🆕 Nuevo modo: {nuevo_modo}")
    try:
        # 1️⃣ Actualizar Google Sheets
        print(f"   📤 Actualizando Google Sheets...")
        actualizar_sheet(numero, nuevo_modo)
        print(f"   ✅ Google Sheets actualizado")
    except Exception as e:
        print(f"   ⚠️  Error actualizando Sheets: {e}")
        # Continuar de todas formas - la memoria es lo importante
 
    # 2️⃣ Actualizar memory_store
    with lock:
        print(f"   🔒 Adquirido lock")
        
        if numero in memory_store:
            print(f"   ✅ Usuario encontrado en memory_store")
            memory_store[numero]["modo"] = nuevo_modo
            memory_store[numero]["last_mode_check"] = time.time()
            print(f"   ✅ Modo cambiado a {nuevo_modo} en memoria")
        else:
            print(f"   ⚠️  Usuario NO encontrado en memory_store")
            # Crear entrada si no existe
            memory_store[numero] = {
                "historial": deque(maxlen=MAX_MENSAJES),
                "last_update": time.time(),
                "modo": nuevo_modo,
                "last_mode_check": time.time(),
                "last_message_time": time.time()
            }
            print(f"   ✅ Usuario creado en memory_store con modo {nuevo_modo}")
        
        print(f"   🔓 Lock liberado\n")

def guardar_interaccion(numero, role, mensaje):
    print(f"\n💾 GUARDAR_INTERACCION iniciado")
    print(f"   📱 Número: {numero}")
    print(f"   👤 Role: {role}")
    print(f"   💬 Mensaje: {mensaje[:60]}...")
    if role not in ("user", "assistant"):
        print(f"   ❌ Role inválido: {role}")
        raise ValueError("role inválido")

    with lock:
        limpiar_expirados()
        if numero not in memory_store:
            if len(memory_store) >= MAX_USERS:
                print(f"   ⚠️  Max usuarios alcanzado. Eliminando el más antiguo...")
                eliminar_mas_antiguo()
 
            memory_store[numero] = {
                "historial": deque(maxlen=MAX_MENSAJES),
                "last_update": time.time(),
                "modo": "AUTO",
                "last_mode_check": 0
            }
            print(f"   ✅ Usuario creado en memory_store")
        else:
            print(f"   ✅ Usuario encontrado en memory_store")
 
        data = memory_store[numero]
 
        # Agregar mensaje
        data["historial"].append({
            "role": role,
            "content": mensaje
        })
        
        print(f"   📊 Historial ahora tiene {len(data['historial'])} mensajes")
        print(f"   ✅ Mensaje guardado en memoria")
        
        data["last_update"] = time.time()
        
    print(f"   🔓 Lock liberado\n")
    print(f"   2️⃣ Sincronizando con Google Sheets...")
    try:
        sheet = iniciar_google()
        if not sheet:
            print(f"   ⚠️  Google Sheets no disponible (no crítico)")
            return
        
        data_sheet = sheet.get_all_records()
        
        # Buscar cliente en Sheets
        fila_existente = None
        for i, row in enumerate(data_sheet):
            if str(row.get("Numero", "")).strip() == str(numero).strip():
                fila_existente = i + 2
                break
        
        if not fila_existente:
            print(f"   ⚠️  Cliente no encontrado en Sheets (no crítico)")
            return
        
        # Leer historial actual de Sheets
        historial_actual = data_sheet[fila_existente - 2].get("Historial", "") or ""
        
        # Construir nuevo mensaje
        if role == "user":
            nuevo = f"Cliente: {mensaje}"
        else:
            nuevo = f"BOT: {mensaje}"
        
        # Unir
        if historial_actual.strip():
            contexto_final = historial_actual + " | " + nuevo
        else:
            contexto_final = nuevo
        
        # Guardar en Sheets (columna 5 = Historial)
        sheet.update_cell(fila_existente, 5, contexto_final)
        
        print(f"   ✅ Google Sheets sincronizado ({len(contexto_final)} chars)")
        
    except Exception as e:
        print(f"   ⚠️  Error sincronizando Sheets: {str(e)}")
        print(f"      (Memory_store ya tiene los datos, no es crítico)")
    
    print(f"   ✅ GUARDADO COMPLETADO (memory + sheets)\n")

def obtener_historial(numero):
    with lock:
        data = memory_store.get(numero)

        if not data:
            return []

        if time.time() - data["last_update"] > EXPIRATION_TIME:
            del memory_store[numero]
            return []
        return list(data["historial"])


def limpiar_expirados():
    ahora = time.time()

    for numero in list(memory_store.keys()):
        if ahora - memory_store[numero]["last_update"] > EXPIRATION_TIME:
            del memory_store[numero]


def eliminar_mas_antiguo():
    usuario_mas_antiguo = min(
        memory_store,
        key=lambda k: memory_store[k]["last_update"]
    )
    del memory_store[usuario_mas_antiguo]

def auto_cerrar_chats_inactivos():
    """Cierra chats sin actividad hace 1 hora"""
    INACTIVIDAD_LIMIT = 3600  # 1 hora en segundos
    
    with lock:
        ahora = time.time()
        for numero, data in list(memory_store.items()):
            ultimo_mensaje = data.get("last_message_time", ahora)
            
            # Si pasó 1 hora sin mensajes y está en HUMANO
            if (ahora - ultimo_mensaje > INACTIVIDAD_LIMIT and 
                data.get("modo") == "HUMANO"):
                
                data["modo"] = "CERRADO"
                print(f"⏱️ Auto-cerrado: {numero} (1 hora de inactividad)")
                actualizar_sheet(numero, "CERRADO")