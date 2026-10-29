import io
import re
import fitz  # PyMuPDF
from PIL import Image
import streamlit as st

st.set_page_config(page_title="Anonimizador de Reportes", page_icon="🔒", layout="centered")

st.title("🔒 Limpiador de Reportes (Equifax / Experian)")
st.write("Oculta **apellidos**, DNI, RUC y usuario consultante con **efecto pixelado**, manteniendo nombres y fechas visibles.")

ETIQUETAS_USUARIO = [
    "Usuario:", "Solicitado por:", "Consultado por:", "Cliente:", 
    "Razón Social Solicitante:", "Generado por:", "Entidad Solicitante:"
]

PATRON_DNI = re.compile(r'^\d{8}$')
PATRON_RUC = re.compile(r'^(10|20|15|17)\d{9}$')

def es_fecha(texto):
    """Detecta si una palabra contiene formato de fecha o separadores"""
    return "/" in texto or "-" in texto or ":" in texto or "." in texto

def extraer_apellidos(doc):
    """Identifica con precisión los apellidos del titular en el documento"""
    apellidos = set()
    nombres_prohibidos = set()
    
    for page in doc:
        text = page.get_text("text")
        
        # 1. Buscar patrón con coma: 'APELLIDO1 APELLIDO2, NOMBRE1 NOMBRE2'
        coincidencias_coma = re.findall(
            r'([A-ZÁÉÍÓÚÑ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ]{2,})?)\s*,\s*([A-ZÁÉÍÓÚÑ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ]{2,})*)', 
            text
        )
        for ap, nom in coincidencias_coma:
            for w in ap.split():
                if len(w) > 2 and w not in ["DEL", "LOS", "LAS", "SAN", "SANTA"]:
                    apellidos.add(w.upper())
            for w in nom.split():
                nombres_prohibidos.add(w.upper())

        # 2. Buscar por bloques y líneas cercanas a etiquetas de nombre
        lines = page.get_text("lines")
        for i, line in enumerate(lines):
            line_str = "".join([span["text"] for span in line.get("spans", [])]).strip()
            
            for etiqueta in ["Apellidos y Nombres", "Nombre / Razón Social", "Nombre/Razón Social", "Titular:"]:
                if etiqueta.lower() in line_str.lower():
                    # El valor puede estar en la misma línea o en la siguiente
                    texto_a_revisar = line_str.replace(etiqueta, "").strip()
                    if not texto_a_revisar and i + 1 < len(lines):
                        texto_a_revisar = "".join([span["text"] for span in lines[i+1].get("spans", [])]).strip()
                    
                    partes = [p for p in re.split(r'[^A-ZÁÉÍÓÚÑa-z]+', texto_a_revisar) if len(p) > 2]
                    if "," in texto_a_revisar:
                        antes_coma = texto_a_revisar.split(",")[0]
                        for w in re.split(r'[^A-ZÁÉÍÓÚÑa-z]+', antes_coma):
                            if len(w) > 2:
                                apellidos.add(w.upper())
                    elif len(partes) >= 3:
                        # Formato peruano común: Paterno Materno Nombres
                        apellidos.add(partes[0].upper())
                        apellidos.add(partes[1].upper())
                        for nom in partes[2:]:
                            nombres_prohibidos.add(nom.upper())
                            
    # Garantizar que ningún nombre de pila se marque por error como apellido
    for n in nombres_prohibidos:
        if n in apellidos:
            apellidos.remove(n)
            
    return apellidos

def censurar_pdf(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    
    # Extraer apellidos del titular en todo el reporte
    apellidos_a_pixelar = extraer_apellidos(doc)
    
    for page in doc:
        rects_a_pixelar = []
        words = page.get_text("words")  # (x0, y0, x1, y1, "texto", block_no, line_no, word_no)
        
        for w in words:
            texto_raw = w[4]
            palabra_limpia = re.sub(r'[^A-ZÁÉÍÓÚÑa-z0-9]', '', texto_raw)
            
            # 1. Censurar SOLO APELLIDOS (Nombres se quedan visibles)
            if palabra_limpia.upper() in apellidos_a_pixelar:
                rects_a_pixelar.append(fitz.Rect(w[0], w[1], w[2], w[3]))
                continue
            
            # Si contiene fecha o separadores, NO se censura
            if es_fecha(texto_raw):
                continue
            
            # 2. Censurar DNI (8 dígitos) y RUC (11 dígitos)
            if PATRON_DNI.match(palabra_limpia) or PATRON_RUC.match(palabra_limpia):
                rects_a_pixelar.append(fitz.Rect(w[0], w[1], w[2], w[3]))

        # 3. Censurar usuario consultante (ancho seguro de 130px sin tapar fechas adyacentes)
        for etiqueta in ETIQUETAS_USUARIO:
            matches = page.search_for(etiqueta)
            for rect in matches:
                rects_a_pixelar.append(fitz.Rect(rect.x0, rect.y0 - 1, rect.x1 + 130, rect.y1 + 1))

        # 4. APLICAR EFECTO PIXELEADO / MOSAICO
        imagenes_pixeladas = []
        for rect in rects_a_pixelar:
            pix = page.get_pixmap(clip=rect, dpi=150)
            if pix.width < 4 or pix.height < 4:
                continue
            
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            # Reducción drástica y ampliación sin suavizado (efecto mosaico)
            w_small = max(2, int(pix.width / 9))
            h_small = max(2, int(pix.height / 7))
            img_small = img.resize((w_small, h_small), resample=Image.Resampling.BILINEAR)
            img_pix = img_small.resize((pix.width, pix.height), resample=Image.Resampling.NEAREST)
            
            img_bytes = io.BytesIO()
            img_pix.save(img_bytes, format="PNG")
            img_bytes.seek(0)
            imagenes_pixeladas.append((rect, img_bytes.getvalue()))

        # Borrar texto original con máscara limpia
        for rect in rects_a_pixelar:
            page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions()

        # Insertar imagen pixelada sobre el hueco
        for rect, img_data in imagenes_pixeladas:
            page.insert_image(rect, stream=img_data)

    output_stream = io.BytesIO()
    doc.save(output_stream, garbage=4, deflate=True)
    doc.close()
    output_stream.seek(0)
    return output_stream

uploaded_file = st.file_uploader("Arrastra o selecciona el reporte en PDF", type=["pdf"])

if uploaded_file is not None:
    st.info(f"Reporte cargado: **{uploaded_file.name}**")
    
    if st.button("🚀 Ocultar Datos Sensibles"):
        with st.spinner("Pixelando apellidos, DNI y usuario..."):
            pdf_limpio = censurar_pdf(uploaded_file.read())
            st.success("¡Documento procesado con éxito!")
            
            st.download_button(
                label="📥 Descargar PDF Limpio",
                data=pdf_limpio,
                file_name=uploaded_file.name.replace(".pdf", "_anonimizado.pdf"),
                mime="application/pdf"
            )
