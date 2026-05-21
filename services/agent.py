from services.ia_service import clasificar_intencion, generar_respuesta_ia
from services.tools import registrar_lead, seguimiento_asesor
from services.memory import cambiar_modo, guardar_interaccion, obtener_historial, obtener_modo
from services.tools import registrar_lead, send_alert, iniciar_google
import os
import re

LINK_ASESOR = "https://wa.me/51988225719"

def ejecutar_agente(numero, empresa, mensaje):
    print(f"\n{'='*70}")
    print(f"🤖 AGENTE INICIADO")
    print(f"   ✅ Usuario: {numero}")
    print(f"   ✅ Empresa: {empresa.get('nombre', '?')}")
    print(f"   ✅ Mensaje del cliente: {mensaje[:50]}")
    print(f"{'='*70}\n")
    historial = obtener_historial(numero)
    mensaje_existe = any(h.get("content") == mensaje and h.get("role") == "user" for h in historial[-3:])
    if not mensaje_existe:
        guardar_interaccion(numero, "user", mensaje)
        print(f"✅ Mensaje guardado")
    else:
        print(f"⚠️  Mensaje ya existe en historial (reintento ignorado)")
    
    respuesta = None
    # Crear contexto
    contexto = ""
    for h in historial[-20:]:
        rol = "Cliente" if h["role"] == "user" else "BOT"
        contexto += f"{rol}: {h['content']} | "
    contexto += f"BOT: {respuesta}"
    


    try:
        sheet = iniciar_google()
        columna_numeros = sheet.col_values(3)
        
        for i, valor in enumerate(columna_numeros[1:], start=2):
            if str(valor).strip() == str(numero):
                # Leer y sumar
                historial_actual = sheet.cell(i, 5).value or ""
                nuevo_mensaje_cliente = f"Cliente: {mensaje}"
                if historial_actual:
                    contexto_final = historial_actual + " | " + nuevo_mensaje_cliente
                else:
                    contexto_final = nuevo_mensaje_cliente
                
                # Guardar
                sheet.update_cell(i, 5, contexto_final)
                break
    except Exception as e:
        print(f"⚠️  Error: {e}")
    respuesta = None
    if not historial:
            print("⚠️  ADVERTENCIA: Historial vacío (usuario nuevo)")
            historial = []
    print(f"\n📜 Historial dentro de ejecutar_agente {numero}:\n{historial}\n")

    intent = clasificar_intencion(mensaje, historial)
    modo = obtener_modo(numero)
    print(f"🔄 Modo: {modo}\n")
    if modo == "CATALOGO":
        msg = mensaje.lower().strip()
        ruta_varon = "static/catalogo_hombre.pdf"
        ruta_dama = "static/catalogo_dama.pdf"
        ruta_nino = "static/catalogo_nino.pdf"
        ruta_futbol = "static/catalogo_futbol.pdf"
        mensaje_sin_catalogo = "Debido a la gran demanda por el CYBER NEW SNEAKERS, estamos actualizando nuestro catálogo en tiempo real para mostrarte solo lo que queda en stock.\n🚀 ¿Cómo comprar ahora mismo?\n1. Visítanos en tienda física: ¡Es la mejor opción! Aseguras tu talla y modelo favorito antes de que se agoten.\n2. Háblanos en las próximas horas: Te enviaremos fotos de los modelos que sigan disponibles."
        if modo == "CATALOGO":
            if any(x in msg for x in ["hombre", "varon", "varón", "caballero"]):
                if os.path.exists(ruta_varon):
                    respuesta = "__CATALOGO_VARON__"
                    cambiar_modo(numero, "AUTO")
                else:
                    respuesta = mensaje_sin_catalogo

            elif any(x in msg for x in ["mujer", "dama", "señora", "senora"]):
                if os.path.exists(ruta_dama):
                    respuesta = "__CATALOGO_DAMA__"
                    cambiar_modo(numero, "AUTO")
                else:
                    respuesta = mensaje_sin_catalogo

            elif any(x in msg for x in ["niño", "nino", "niña", "nina", "niños"]):
                if os.path.exists(ruta_nino):
                    respuesta = "__CATALOGO_NINO__"
                    cambiar_modo(numero, "AUTO")
                else:
                    respuesta = mensaje_sin_catalogo
            
            elif any(x in msg for x in ["futbol", "fútbol", "chimpun", "chimpunes", "choteras"]):
                if os.path.exists(ruta_futbol):
                    respuesta = "__CATALOGO_FUTBOL__"
                    cambiar_modo(numero, "AUTO")
                else:
                    respuesta = mensaje_sin_catalogo
            else: 
                respuesta = "😊 Indícame por favor una categoría:\n👠 Dama\n👟 Varón\n👧 Niño\n⚽ Fútbol"
            if respuesta.startswith("__CATALOGO_"):
                registrar_lead(numero, mensaje, empresa, historial, intent="catalogo",skip_history=True)
            return respuesta
           

    if intent == "duda":
        if re.search(r'\b(por mayor|al por mayor|mayorista|precio(s)? por mayor|venta(s)? por mayor)\b', mensaje.lower().strip()):
            respuesta = "Hola!, Excelente! 🌟 Para brindarte precios de Mayorista, por favor confímanos:\n1. ¿Eres persona natural o empresa?\n2. ¿En qué ciudad y/o provincia te encuentras? (Para coordinar envío o entrega en Arequipa)\nCondiciones:\n✅ Mínimo una docena por modelo.\n✅ El paquete viene seriado (mismo modelo).\nQuedo atento 🚀"
        else:
            respuesta = generar_respuesta_ia(mensaje, empresa, historial)
            if "asesor" in respuesta.lower() or "contactará" in respuesta.lower():
                respuesta += f"\n\nPara continuar con tu atención, por favor haz clic en el siguiente enlace y escríbenos directamente por WhatsApp:{LINK_ASESOR}"
                send_alert(empresa["email"], respuesta, empresa, numero, historial)
                seguimiento_asesor(numero, mensaje,empresa,historial,skip_history=True)
                cambiar_modo(numero, "HUMANO")

    elif intent == "saludo":
        respuesta = generar_respuesta_ia(mensaje, empresa, historial)
        if "asesor" in respuesta.lower() or "contactará" in respuesta.lower():
            respuesta += f"\n\nPara continuar con tu atención, por favor haz clic en el siguiente enlace y escríbenos directamente por WhatsApp:{LINK_ASESOR}"
            send_alert(empresa["email"], respuesta, empresa, numero, historial)
            seguimiento_asesor(numero, mensaje,empresa,historial,skip_history=True)
            cambiar_modo(numero, "HUMANO")
            
    elif any(x in intent for x in ["compra", "agendamiento"]):
        registrar_lead(numero, mensaje, empresa,historial, intent=intent,skip_history=True)
        send_alert( empresa["email"],mensaje,empresa,numero,historial)
        respuesta = f"¡Perfecto! Ya registramos tu solicitud. Un asesor te contactará enseguida\n\nPara continuar con tu atención, por favor haz clic en el siguiente enlace y escríbenos directamente por WhatsApp:{LINK_ASESOR}"
        cambiar_modo(numero, "HUMANO")
        
    
    elif "catalogo" in intent:
        respuesta = "✨ Con gusto te comparto nuestro catálogo. Manejamos las mejores marcas: New Athletic, Irun, Walon (solo fútbol), Dariems y Dromedar (solo urbana caña alta), todas importadas; además de Ivano, que es cuero nacional. 🇵🇪\n¿En qué categoría estás interesado?\n* 👠 Dama\n* 👟 Varón\n* 👧 Niño\n* ⚽ Fútbol\nTips de tallas:\n* 🌍 Importadas: La horma es pequeña.\n* 🇵🇪 Ivano: Cuero nacional de horma completa."
        cambiar_modo(numero, "CATALOGO")
        return respuesta

    elif "promociones" in intent:
        respuesta = "¡Hola! 👋 Por ahora no tenemos promociones activas, pero ¡mantente alerta! 🚨 Ya estamos alistando los mejores modelos y sorpresas para celebrar el Día del Trabajo. 👷‍♂️👟\n¡Se viene un drop increíble que no querrás perderte! 🔥\n¿Hay algo más en lo que pueda ayudarte hoy? 😊"
    
    elif "replica" in intent:
        respuesta = "En New Sneaker somos Distribuidores Autorizados de todas las marcas que ves en nuestro catálogo (New Athletic, I Run, Ivano, Dariem, entre otras).\nEsto nos permite garantizarte que:\n✅ Todos nuestros productos son 100% ORIGINALES.\n✅ Manejamos los más altos estándares de calidad y durabilidad.\n✅ No trabajamos con réplicas ni imitaciones; recibirás un producto auténtico de marca.\nPuedes visitarnos en nuestras tiendas físicas en San Juan de Dios para comprobar la calidad de los materiales tú mismo. ¡Tu inversión y tu comodidad están aseguradas con nosotros! 🏆\nHay algo mas en lo que pueda ayudarte ?"

    elif intent == "queja":
        respuesta = f"Lamentamos lo ocurrido. Un asesor revisará tu caso y te contactará.\n Recuerda que nuestro horario de atención es de Lunes a Viernes de 9:00 AM a 8:00 PM y sabado de 9:00 AM a 8:30 PM."
        send_alert(empresa["email"], respuesta, empresa, numero, historial)
        cambiar_modo(numero, "HUMANO")
    elif intent == "cierre":
        respuesta = generar_respuesta_ia(mensaje, empresa, historial)
        registrar_lead(numero, mensaje, empresa,historial,intent=intent,skip_history=True)
    else:
        respuesta = generar_respuesta_ia(mensaje, empresa, historial)
        if "asesor" in respuesta.lower() or "contactará" in respuesta.lower():
            respuesta += f"\n\nPara continuar con tu atención, por favor haz clic en el siguiente enlace y escríbenos directamente por WhatsApp:{LINK_ASESOR}"
            send_alert(empresa["email"], respuesta, empresa, numero, historial)
            seguimiento_asesor(numero, mensaje,empresa,historial,skip_history=True)
            cambiar_modo(numero, "HUMANO")
        if "agendar" in respuesta or "comprar" in respuesta:
            registrar_lead(numero, mensaje, empresa, historial, intent=intent,skip_history=True)
            cambiar_modo(numero, "HUMANO")
    print("\nINTENT:", intent,"\n")
    if respuesta:
        try:
            guardar_interaccion(numero, "assistant", respuesta)
        
        except Exception as e:
            print(f"⚠️  Error guardando bot: {e}")
    
    return respuesta
  