import base64
import datetime
from email.mime.text import MIMEText
import os
import threading
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from thefuzz import fuzz
import json
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import pytz
from collections import Counter

client = None
sheet_leads = None
zona_horaria = pytz.timezone('America/Lima')

class CacheSheetsManager:
    def __init__(self, ttl_segundos=30):
        self.client = None
        self.sheet_leads = None
        self.cache_datos = None
        self.cache_timestamp = None
        self.ttl = ttl_segundos
        self.lock = threading.Lock()
    def is_cache_valido(self):
        """Verifica si el caché sigue siendo válido"""
        if not self.cache_timestamp:
            return False
        edad = (datetime.datetime.now() - self.cache_timestamp).total_seconds()
        return edad < self.ttl
    def iniciar_google(self):
        with self.lock:
            if self.sheet_leads:
                return self.sheet_leads
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]

        google_info = json.loads(os.getenv("GOOGLE_SHEETS_JSON"))

        creds = ServiceAccountCredentials.from_json_keyfile_dict(
            google_info, scope
        )

        self.client = gspread.authorize(creds)

        archivo = self.client.open("Leads")

        try:
            self.sheet_leads = archivo.worksheet("Leads")
        except:
            self.sheet_leads = archivo.sheet1
        
        headers = [
        "ID",
        "Modo",
        "Numero",
        "Ultimo Mensaje",
        "Historial",
        "Servicio",
        "Empresa",
        "Dia",
        "Hora",
        "Estado",
        "Pais",
        "Dia_Semana",
        "Turno",
        "Intercambios"]

        fila1 = self.sheet_leads.row_values(1)
        if not fila1:
            self.sheet_leads.append_row(headers)

        return self.sheet_leads
    def obtener_todos_datos(self):
        """
        ✅ UNA sola llamada a Google por 30 segundos
        ✅ Las otras usa caché
        """
        if self.is_cache_valido():
            print("⚡ Usando CACHÉ (sin llamar a Google)")
            return self.cache_datos
        
        try:
            sheet = self.iniciar_google()
            if not sheet:
                return []
            
            print("📥 Llamando a Google Sheets (primera vez o caché expirado)")
            self.cache_datos = sheet.get_all_records()
            self.cache_timestamp = datetime.datetime.now()
            
            return self.cache_datos
        
        except Exception as e:
            print(f"❌ Error obteniendo datos: {e}")
            return []
    
    def invalidar_cache(self):
        """Limpia el caché cuando hay cambios"""
        self.cache_timestamp = None
        print("🔄 Caché invalidado")

cache_manager = CacheSheetsManager(ttl_segundos=30)

def iniciar_google():
    """Función compatible - usa caché"""
    return cache_manager.iniciar_google()

def extraer_dia_semana(fecha) -> str:
    dias = {
        0: "Lunes", 1: "Martes", 2: "Miércoles",
        3: "Jueves", 4: "Viernes", 5: "Sábado", 6: "Domingo"
    }
    return dias[fecha.weekday()]

def extraer_turno(fecha) -> str:
    hora = fecha.hour
    if 6 <= hora < 12:
        return "Mañana"
    elif 12 <= hora < 18:
        return "Tarde"
    elif 18 <= hora < 23:
        return "Noche"
    else:
        return "Madrugada"

def contar_intercambios(historial: list) -> int:
    return len(historial)

def extraer_pais(numero: str) -> str:
    numero = str(numero).strip().lstrip("+")
    prefijos = {
        "54": "Argentina",
        "51": "Perú",
        "55": "Brasil",
        "56": "Chile",
        "57": "Colombia",
        "58": "Venezuela",
        "591": "Bolivia",
        "593": "Ecuador",
        "595": "Paraguay",
        "598": "Uruguay",
        "502": "Guatemala",
        "503": "El Salvador",
        "504": "Honduras",
        "505": "Nicaragua",
        "506": "Costa Rica",
        "507": "Panamá",
        "52": "México",
        "1":  "EE.UU. / Canadá",
        "34": "España",
    }
    # Primero intenta prefijos de 3 dígitos, luego 2
    for largo in (3, 2, 1):
        clave = numero[:largo]
        if clave in prefijos:
            return prefijos[clave]
    return "Desconocido"

def buscar_cliente_en_cache(numero):
    """
    ✅ Busca cliente EN CACHÉ sin llamar a Google
    ✅ Si no está, retorna None
    """
    datos = cache_manager.obtener_todos_datos()
    
    for fila_idx, row in enumerate(datos):
        if str(row.get("Numero", "")).strip() == str(numero).strip():
            return {
                "fila": fila_idx + 2,  # +2 por header + indexación
                "datos": row
            }
    
    return None

def buscar_modo_en_sheet(numero):
    try:
        cliente = buscar_cliente_en_cache(numero)
        if cliente:
            modo = cliente["datos"].get("Modo", "AUTO")
            return modo if modo else "AUTO"
        return "AUTO"
    except Exception as e:
        print(f"❌ Error buscando modo: {e}")
        return "AUTO"

def identificar_servicio(historial,empresa):
    servicios = empresa.get("categorias", {}).keys()
    if not servicios:
        return "No identificado"

    mensaje = [h["content"].lower() for h in historial if h["role"] == "user"]
    texto_completo = " ".join(mensaje)
    palabras = texto_completo.split()
    conteo = Counter()

    for servicio in servicios:
        nombre = servicio.lower()

        if nombre in texto_completo:
            conteo[servicio] += texto_completo.count(nombre)
            continue

        for palabra in palabras:
            if fuzz.partial_ratio(nombre, palabra) >= 80:
                conteo[servicio] += 1
                break
    if not conteo:
        return "No identificado"
    categoria_favorita = conteo.most_common(1)[0][0]
    return categoria_favorita

def registrar_lead(numero, mensaje, empresa,historial, modo="AUTO",intent=None):
    print("Ejecutando registro de lead...")
    try:
        sheet = iniciar_google()
        if not sheet:
            print("❌ Sheets no disponible")
            return

        fecha = datetime.datetime.now(zona_horaria)
        cliente = buscar_cliente_en_cache(numero)
        nuevo_registro = f"Cliente: {mensaje}"
        try:
            if cliente:
                historial_actual = cliente["datos"].get("Historial", "") or ""
                if historial_actual:
                    contexto_final = historial_actual + " | " + nuevo_registro
                else:
                    contexto_final = nuevo_registro
                estado = "Atendido por el bot" if intent == "cierre" else "Pendiente Asesor"
            else:
                contexto_final = nuevo_registro
                estado = "Pendiente Asesor"    
        except Exception as e:
            print(f"⚠️  Error actualizando: {e}")

        servicios = identificar_servicio(historial, empresa)
        pais = extraer_pais(numero)

        dia_semana    = extraer_dia_semana(fecha)
        turno         = extraer_turno(fecha)
        intercambios  = contar_intercambios(historial)

        if cliente:

            sheet.update(f"D{cliente['fila']}:N{cliente['fila']}",[[
                mensaje,
                contexto_final,
                servicios,
                empresa["nombre"],
                fecha.strftime("%d-%m-%Y"),
                fecha.strftime("%H:%M"),
                estado,
                pais,
                dia_semana,                  
                turno,                       
                intercambios 
            ]])

            print("✅ Cliente actualizado")

        else:

            fila = [
                len(cache_manager.obtener_todos_datos()) + 1,
                modo,
                numero,
                mensaje,
                contexto_final,
                servicios,
                empresa["nombre"],
                fecha.strftime("%d-%m-%Y"),
                fecha.strftime("%H:%M"),
                estado,
                pais,
                dia_semana,                  
                turno,                       
                intercambios 
            ]

            sheet.append_row(fila)

            print("✅ Lead guardado Nuevo cliente")

    except Exception as e:
        print("❌ Error lead:", e)

def send_alert(email,mensaje, empresa, numero,historial):
    try:
        token_data = json.loads(os.getenv("GMAIL_TOKEN_JSON"))
        creds = Credentials.from_authorized_user_info(token_data)
        service = build('gmail', 'v1', credentials=creds)

        contexto = ""

        for h in historial[-10:]:  # últimos 10 mensajes
            rol = "Cliente" if h["role"] == "user" else "Bot"
            contexto += f"\n{rol}: {h['content']}\n"

        cuerpo = f"""
        🔥 NUEVO LEAD DETECTADO

        Empresa: {empresa['nombre']}
        Cliente: {numero}

        🧾 --- Resumen del chat ---:
        {contexto}

        📩 Último mensaje:
        {mensaje}"""

        msg = MIMEText(cuerpo)
        msg['subject'] = 'Nuevo Lead Interesado'
        msg['To'] = email
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(userId='me', body={'raw': raw}).execute()
        print(f"✅ Alerta enviada con éxito a {email}")
    except Exception as e:
        print("Error al enviar email:", (e))

    print(f"📧 Enviando alerta a {email}: {mensaje}")

def actualizar_sheet(numero, nuevo_modo):
    try:
        sheet = iniciar_google()

        columna_numeros = sheet.col_values(3)

        for i, valor in enumerate(columna_numeros[1:], start=2):
            if str(valor).strip() == str(numero):
                sheet.update_cell(i, 2, nuevo_modo)
                print(f"ACTUALIZAR_SHEET : ✅ {numero} cambiado a {nuevo_modo}")
                return True
        return False

    except Exception as e:
        print("❌ Error actualizando modo:", e)
        return False
    
def seguimiento_asesor(numero, mensaje,respuesta, empresa,historial, modo="AUTO"):
    print("Ejecutando seguimiento asesor...")
    try:
        sheet = iniciar_google()

        fecha = datetime.datetime.now(zona_horaria)

        try:
            # Leer historial actual
            historial_actual = sheet.cell(fila_existente, 5).value or ""  # Columna E (5)
            
            nuevo_registro = f"Cliente: {mensaje}"
            
            # Sumar
            if historial_actual:
                contexto_final = historial_actual + " | " + nuevo_registro
            else:
                contexto_final = nuevo_registro

            
        except Exception as e:
            print(f"⚠️  Error actualizando: {e}") 

        servicios = identificar_servicio(historial, empresa)
        pais = extraer_pais(numero)

        dia_semana    = extraer_dia_semana(fecha)
        turno         = extraer_turno(fecha)
        intercambios  = contar_intercambios(historial)

        columna_numeros = sheet.col_values(3)

        fila_existente = None

        for i, valor in enumerate(columna_numeros[1:], start=2):
            if str(valor).strip() == str(numero):
                fila_existente = i
                break
        
        print("Fila encontrada:", fila_existente)
        
        if fila_existente:

            sheet.update(f"D{fila_existente}:N{fila_existente}",[[
                mensaje,
                contexto_final,
                servicios,
                empresa["nombre"],
                fecha.strftime("%d-%m-%Y"),
                fecha.strftime("%H:%M"),
                "Pendiente Asesor",
                pais,
                dia_semana,                  
                turno,                       
                intercambios 
            ]])

            print("✅ Cliente actualizado seguimiento asesor!")

        else:

            fila = [
                len(sheet.col_values(1)),   # ID rápido
                modo,
                numero,
                mensaje,
                contexto_final,
                servicios,
                empresa["nombre"],
                fecha.strftime("%d-%m-%Y"),
                fecha.strftime("%H:%M"),
                "Pendiente Asesor",
                pais,
                dia_semana,                  
                turno,                       
                intercambios 
            ]

            sheet.append_row(fila)

        print("✅ SEGUIMIENTO ASESOR")

    except Exception as e:
        print("❌ Error lead:", e)
