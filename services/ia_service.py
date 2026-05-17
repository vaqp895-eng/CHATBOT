import os 
import json
from dotenv import load_dotenv
from google.oauth2 import service_account
import vertexai
from vertexai.generative_models import GenerativeModel

load_dotenv()

google_json_str = os.getenv("GOOGLE_SHEETS_JSON")

if google_json_str:
    google_info = json.loads(google_json_str)
    creds = service_account.Credentials.from_service_account_info(google_info)
else:
    print("❌ Error: No se encontró GOOGLE_SHEETS_JSON para inicializar la IA")
    creds = None

PROJECT_ID = "project-2641fa03-f32f-4d6f-ba8"
LOCATION = "us-central1"

vertexai.init(project=PROJECT_ID, location=LOCATION, credentials=creds)
model = GenerativeModel("gemini-2.5-flash")

#gemini-3.1-flash-lite-preview
def clasificar_intencion(mensaje, historial):
    context = ""
    for h in historial[-3:]:
        context += f"{h['role']}: {h['content']}\n"

    prompt = f"""
    Clasifica el mensaje en UNA sola palabra de estas opciones: [saludo, duda, compra, queja, promociones, catalogo, replica,cierre].

    Reglas:
    - "compra": Solo si usa frases directas ("quiero agendar", "puedo agendar", "quiero comprar", "cómo compro", etc.)si preguntan por el catalogo categorizalo mejor en catalogo
    - "duda": Precios, interés general , informacion ("me interesa","cuánto cuesta","cómo funciona") o funcionamiento.No asumas compra.
    - "saludo" / "queja": Según contenido evidente.
    - "promociones": Si pregunta por ofertas o promocion.
    - "replica": Si pregunta por originalidad/réplica.
    - "catalogo": Si pide catálogo, zapatillas (dama/varón) o modelos específicos. (a menos que pidan comprar ahi catelogizalo como compra)
    - Nunca infieras intención de compra o agendamiento si no está claramente expresada por el cliente.
    - "cierre": Si el cliente esta satisfecho y se despide o da por concluida la conversación.

    Mensaje:{mensaje}
    Historial:{context}
    Respuesta:"""
    try:
        response = model.generate_content(prompt)
        return response.text.strip().lower()
    except Exception as e:
        print("Error IA:", e)
        return "duda"

def generar_respuesta_ia(mensaje, empresa, historial):

    contexto = ""

    for h in historial[-5:]:
        if h["role"] == "user":
            contexto += f"user: {h['content']}\n"
        else:
            contexto += f"assistant: {h['content']}\n"

    prompt = f"""
    Eres un asistente virtual de {empresa['nombre']} atención al cliente,Estilo: amigable,profesional,breve.Usa emojis.  
    Objetivo: {empresa['objetivo']}

    DATOS EMPRESA:
    - Info: {empresa['descripcion']} 
    - Horario: {empresa['horario']} | Ubicación: {empresa['ubicacion']},arequipa.
    - Productos: {empresa['marcas_disponibles']} (importados poseen una horma pequeña, recomendamos llevar una talla más de la habitual)
    - Pagos/Envíos: {empresa['pagos']} Envío a cargo del cliente.El precio exacto se consulta indicando ubicación/departamento.
    - Cambios/devoluciones: {empresa['politica_cambios']}

    Reglas:
    - Si el historial muestra varias preguntas del usuario sin responder, dales una sola respuesta unificada
    - Si no te estan saludando, no saludes tú tampoco. Responde directamente a lo que te preguntan.
    - NO saludes si la conversación ya está en curso (mira el contexto previo)
    - Responde SOLO lo pedido basándote exclusivamente en el contexto. Responde solo lo que te piden.
    - Si desconoces algo, di: "No tengo esa información,un asesor te contactará".
    - Si piden fotos,tallas,precios, ofrece el catálogo (indica que escriban "catalogo").
    - No asumas intención de compra ni hagas seguimiento comercial proactivo.
    - Si el cliente saluda, responde amablemente y ofrece ayuda
    - Flujo Envíos: Si preguntan por envíos, brinda la info y pregunta: "¿Deseas realizar un envío?". SOLO si el cliente confirma (ej. "sí"), manda a asesor.No mandes al asesor antes de la confirmación.

    Contexto previo:{contexto}
    Cliente: {mensaje}
    Respuesta(sin saludos innecesarios):"""
    #Si no sabes, di: "No tengo esa información, un asesor te contactará".
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print("Error IA:", e)
        return "⚠️ Un asesor te responderá en breve."
    
def generar_sugerencias(historial):
    """Genera 2 sugerencias de respuesta basadas en el chat"""
    try:
        # Construir contexto con últimos 3 mensajes
        context = ""
        for h in historial[-3:]:
            role = "Cliente" if h['role'] == 'user' else "Asesor"
            context += f"{role}: {h['content']}\n"
        
        if not context.strip():
            return [
                "¿En qué te puedo ayudar?",
                "Cuéntame más detalles"
            ]
        
        prompt = f"""Basándote en esta conversación, genera EXACTAMENTE 2 sugerencias cortas (máx 60 caracteres cada una) para responder al cliente. 
Conversación:
{context}
Formato:
1. [Primera sugerencia]
2. [Segunda sugerencia]
Solo responde con las 2 sugerencias, sin explicaciones."""

        response = model.generate_content(prompt)
        texto = response.text.strip()
        
        # Parsear las sugerencias
        sugerencias = []
        for line in texto.split("\n"):
            line = line.strip()
            if line and line[0].isdigit():
                # Extraer texto después del número y punto
                if ". " in line:
                    sugerencia = line.split(". ", 1)[1]
                else:
                    sugerencia = line
                
                # Limpiar caracteres especiales
                sugerencia = sugerencia.strip("[]")
                sugerencias.append(sugerencia)
        
        # Devolver solo 2 sugerencias
        if len(sugerencias) >= 2:
            return sugerencias[:2]
        elif len(sugerencias) == 1:
            return sugerencias + ["¿Hay algo más que quieras saber?"]
        else:
            return [
                "¿En qué más te ayudo?",
                "¿Tienes alguna otra pregunta?"
            ]
            
    except Exception as e:
        print(f"❌ Error generando sugerencias: {e}")
        return [
            "¿En qué te puedo ayudar?",
            "Cuéntame más detalles"
        ]