import io
import re
import fitz  # PyMuPDF
from PIL import Image
import streamlit as st

st.set_page_config(page_title="Anonimizador de Reportes", page_icon="🔒", layout="centered")

st.title("🔒 Limpiador de Reportes (Equifax / Experian)")
st.write("Censura apellidos, DNI, RUC y usuario consultante con **efecto pixelado**, manteniendo nombres y fechas visibles.")

# Etiquetas del consultante
ETIQUETAS_USUARIO = [
    "Usuario:", "Solicitado por:", "Consultado por:", "Cliente:", 
    "Razón Social Solicitante:", "Generado por:", "Entidad Solicitante:"
]

PATRON_DNI = re.compile(r'^\d{8}$')
PATRON_RUC = re.compile(r'^(10|20|15|17)\d{9}$')

def es_fecha(texto):
    """Detecta si una palabra contiene formato de fecha o separadores"""
    return "/" in texto or "-" in texto or ":" in texto or "." in texto

def censurar_pdf(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    
    for page in doc:
        rects_a_pixelar = []
        words = page.get_text("words")  # (x0, y0, x1, y1, "texto", block_no, line_no, word_no)
        
        # 1. Censurar únicamente DNI y RUC (protegiendo fechas)
        for w in words:
            texto_raw = w[4]
            # Si contiene separadores de fecha o hora, NO se toca
            if es_fecha(texto_raw):
                continue
            
            palabra = re.sub(r'[^\w]', '', texto_raw)
            if PATRON_DNI.match(palabra) or PATRON_RUC.match(palabra):
                rects_a_pixelar.append(fitz.Rect(w[0], w[1], w[2], w[3]))

        # 2. Censurar usuario consultante (ancho moderado para no tapar fechas adyacentes)
        for etiqueta in ETIQUETAS_USUARIO:
            matches = page.search_for(etiqueta)
            for rect in matches:
                # Solo tapamos el nombre del usuario (máximo 140px a la derecha), sin tocar fechas
                rects_a_pixelar.append(fitz.Rect(rect.x0, rect.y0 - 1, rect.x1 + 140, rect.y1 + 1))

        # 3. Censurar SOLO APELLIDOS (Dejar Nombres visibles)
        # En Perú el formato es: Paterno Materno Nombres
        for etiqueta in ["Apellidos y Nombres:", "Nombre / Razón Social:", "Titular:"]:
            matches = page.search_for(etiqueta)
            for rect in matches:
                # Buscamos las palabras que siguen en esa misma línea
                palabras_linea = [
                    w for w in words 
                    if abs(w[1] - rect.y0) < 6 and w[0] > rect.x1
                ]
                palabras_linea.sort(key=lambda x: x[0])
                
                # Si hay coma (ej. PEREZ GARCIA, PEISER BELOMAR):
                palabras_apellidos = []
                tiene_coma = any("," in w[4] for w in palabras_linea)
                
                if tiene_coma:
                    for w in palabras_linea:
                        palabras_apellidos.append(w)
                        if "," in w[4]:
                            break
                else:
                    # Si no hay coma, tomamos solo los primeros 2 términos (Apellidos)
                    palabras_apellidos = palabras_linea[:2]
                
                for w in palabras_apellidos:
                    rects_a_pixelar.append(fitz.Rect(w[0], w[1], w[2], w[3]))

        # Si el reporte tiene campos separados específicos de apellidos:
        for etiq_ap in ["Apellido Paterno:", "Apellido Materno:"]:
            matches = page.search_for(etiq_ap)
            for rect in matches:
                palabras_valor = [
                    w for w in words 
                    if abs(w[1] - rect.y0) < 6 and w[0] > rect.x1
                ]
                if palabras_valor:
                    w = palabras_valor[0]
                    rects_a_pixelar.append(fitz.Rect(w[0], w[1], w[2], w[3]))

        # 4. APLICAR EFECTO PIXELEADO REAL
        imagenes_pixeladas = []
        for rect in rects_a_pixelar:
            # Capturar recorte de la zona
            pix = page.get_pixmap(clip=rect, dpi=150)
            if pix.width < 4 or pix.height < 4:
                continue
            
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            # Efecto pixelado / mosaico
            w_small = max(2, int(pix.width / 9))
            h_small = max(2, int(pix.height / 7))
            img_small = img.resize((w_small, h_small), resample=Image.Resampling.BILINEAR)
            img_pix = img_small.resize((pix.width, pix.height), resample=Image.Resampling.NEAREST)
            
            img_bytes = io.BytesIO()
            img_pix.save(img_bytes, format="PNG")
            img_bytes.seek(0)
            imagenes_pixeladas.append((rect, img_bytes.getvalue()))

        # Borrado de texto interno (seguridad) y reemplazo por imagen pixelada
        for rect in rects_a_pixelar:
            page.add_redact_annot(rect, fill=(1, 1, 1))  # Fondo blanco limpio
        page.apply_redactions()

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
        with st.spinner("Aplicando efecto pixelado a datos sensibles..."):
            pdf_limpio = censurar_pdf(uploaded_file.read())
            st.success("¡Documento procesado con éxito!")
            
            st.download_button(
                label="📥 Descargar PDF Limpio",
                data=pdf_limpio,
                file_name=uploaded_file.name.replace(".pdf", "_anonimizado.pdf"),
                mime="application/pdf"
            )
