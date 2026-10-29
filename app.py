import io
import re
import fitz  # PyMuPDF
import streamlit as st

st.set_page_config(page_title="Anonimizador de Reportes", page_icon="🔒", layout="centered")

st.title("🔒 Limpiador de Reportes (Equifax / Experian)")
st.write("Sube el PDF de Infocorp o Sentinel para ocultar datos personales.")

# Etiquetas comunes en reportes peruanos
ETIQUETAS_USUARIO = [
    "Usuario:", "Solicitado por:", "Consultado por:", "Cliente:", 
    "Razón Social Solicitante:", "Generado por:", "Entidad Solicitante:"
]

ETIQUETAS_NOMBRE = [
    "Apellidos y Nombres:", "Nombre / Razón Social:", "Titular:", "Nombre:", "Razón Social:"
]

PATRON_DNI = re.compile(r'^\d{8}$')
PATRON_RUC = re.compile(r'^(10|20|15|17)\d{9}$')

def censurar_pdf(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    
    for page in doc:
        rects_a_censurar = []
        
        # 1. Detección de DNI y RUC
        words = page.get_text("words")
        for w in words:
            palabra_limpia = re.sub(r'[^\w]', '', w[4])
            if PATRON_DNI.match(palabra_limpia) or PATRON_RUC.match(palabra_limpia):
                rects_a_censurar.append(fitz.Rect(w[0], w[1], w[2], w[3]))

        # 2. Censurar usuario/solicitante
        for etiqueta in ETIQUETAS_USUARIO:
            matches = page.search_for(etiqueta)
            for rect in matches:
                rects_a_censurar.append(fitz.Rect(rect.x0, rect.y0 - 2, rect.x1 + 300, rect.y1 + 2))

        # 3. Censurar nombres
        for etiqueta in ETIQUETAS_NOMBRE:
            matches = page.search_for(etiqueta)
            for rect in matches:
                rects_a_censurar.append(fitz.Rect(rect.x1 + 4, rect.y0 - 2, rect.x1 + 350, rect.y1 + 2))

        # 4. Censura física irreversible
        for rect in rects_a_censurar:
            page.add_redact_annot(rect, fill=(0, 0, 0))
            
        page.apply_redactions()

    output_stream = io.BytesIO()
    doc.save(output_stream, garbage=4, deflate=True)
    doc.close()
    output_stream.seek(0)
    return output_stream

uploaded_file = st.file_uploader("Arrastra o selecciona el reporte en PDF", type=["pdf"])

if uploaded_file is not None:
    st.info(f"Reporte cargado: **{uploaded_file.name}**")
    
    if st.button("🚀 Ocultar Datos Sensibles"):
        with st.spinner("Procesando documento..."):
            pdf_limpio = censurar_pdf(uploaded_file.read())
            st.success("¡Datos ocultados con éxito!")
            
            st.download_button(
                label="📥 Descargar PDF Limpio",
                data=pdf_limpio,
                file_name=uploaded_file.name.replace(".pdf", "_anonimizado.pdf"),
                mime="application/pdf"
            )
