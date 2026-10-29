import io
import re
import fitz  # PyMuPDF
from PIL import Image
import streamlit as st

st.set_page_config(page_title="Anonimizador de Reportes", page_icon="🔒", layout="centered")

st.title("🔒 Limpiador de Reportes (Equifax / Experian)")
st.write("Oculta apellidos, DNI, RUC y usuario consultante con **efecto pixelado**, manteniendo nombres y fechas visibles.")

ETIQUETAS_USUARIO = [
    "Usuario:", "Solicitado por:", "Consultado por:", "Cliente:", 
    "Razón Social Solicitante:", "Generado por:", "Entidad Solicitante:"
]

PATRON_DNI = re.compile(r'^\d{8}$')
PATRON_RUC = re.compile(r'^(10|20|15|17)\d{9}$')

def es_fecha(texto):
    """Protege fechas y horas para que no se confundan con DNI"""
    return "/" in texto or "-" in texto or ":" in texto or "." in texto

def censurar_pdf(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    apellidos_detectados = set()
    
    for page in doc:
        rects_a_pixelar = []
        words = page.get_text("words")  # (x0, y0, x1, y1, "texto", block_no, line_no, word_no)
        
        # 1. Agrupar palabras por línea para analizar la barra gris de Experian
        lineas = {}
        for w in words:
            y_center = round((w[1] + w[3]) / 2, 0)
            encontrado = False
            for y_key in lineas:
                if abs(y_key - y_center) <= 5:
                    lineas[y_key].append(w)
                    encontrado = True
                    break
            if not encontrado:
                lineas[y_center] = [w]

        # 2. Detectar nombres en la barra: "DNI XXXXXXXX - CACERES YHUQUIMAGO NOE"
        for y_key, line_words in lineas.items():
            line_words.sort(key=lambda x: x[0])
            textos = [w[4] for w in line_words]
            
            tiene_guion = any("-" in t or "–" in t for t in textos)
            tiene_dni = any(t.upper() in ["DNI", "RUC", "CE"] for t in textos)
            
            if tiene_guion or tiene_dni:
                idx_inicio = -1
                for i, w in enumerate(line_words):
                    t = w[4]
                    if "-" in t or "–" in t:
                        idx_inicio = i + 1
                        break
                    # Si viene después del número de DNI
                    num_limpio = re.sub(r'[^\w]', '', t)
                    if num_limpio.isdigit() and len(num_limpio) >= 8:
                        idx_inicio = i + 1
                
                if idx_inicio != -1 and idx_inicio < len(line_words):
                    palabras_nombre = [
                        w for w in line_words[idx_inicio:] 
                        if re.sub(r'[^A-ZÁÉÍÓÚÑa-z]', '', w[4]).isalpha() and len(w[4]) > 1
                    ]
                    
                    # Si hay 3 palabras (CACERES YHUQUIMAGO NOE):
                    # Tapa las 2 primeras (apellidos) y deja la última (NOE)
                    if len(palabras_nombre) >= 3:
                        for ap in palabras_nombre[:2]:
                            rects_a_pixelar.append(fitz.Rect(ap[0], ap[1], ap[2], ap[3]))
                            apellidos_detectados.add(re.sub(r'[^A-ZÁÉÍÓÚÑa-z]', '', ap[4]).upper())
                    elif len(palabras_nombre) == 2:
                        ap = palabras_nombre[0]
                        rects_a_pixelar.append(fitz.Rect(ap[0], ap[1], ap[2], ap[3]))
                        apellidos_detectados.add(re.sub(r'[^A-ZÁÉÍÓÚÑa-z]', '', ap[4]).upper())

        # 3. Censurar DNI, RUC y apellidos que se repitan en el texto
        for w in words:
            texto_raw = w[4]
            palabra_limpia = re.sub(r'[^A-ZÁÉÍÓÚÑa-z0-9]', '', texto_raw)
            
            # Censurar los apellidos detectados si vuelven a aparecer
            if palabra_limpia.upper() in apellidos_detectados:
                rects_a_pixelar.append(fitz.Rect(w[0], w[1], w[2], w[3]))
                continue
            
            # Si es fecha u hora, proteger
            if es_fecha(texto_raw):
                continue
            
            # Censurar números de DNI (8 dígitos) y RUC (11 dígitos)
            if PATRON_DNI.match(palabra_limpia) or PATRON_RUC.match(palabra_limpia):
                rects_a_pixelar.append(fitz.Rect(w[0], w[1], w[2], w[3]))

        # 4. Censurar datos del usuario que generó el reporte
        for etiqueta in ETIQUETAS_USUARIO:
            matches = page.search_for(etiqueta)
            for rect in matches:
                rects_a_pixelar.append(fitz.Rect(rect.x0, rect.y0 - 1, rect.x1 + 130, rect.y1 + 1))

        # 5. APLICAR EFECTO PIXELEADO / MOSAICO
        imagenes_pixeladas = []
        for rect in rects_a_pixelar:
            pix = page.get_pixmap(clip=rect, dpi=150)
            if pix.width < 4 or pix.height < 4:
                continue
            
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            w_small = max(2, int(pix.width / 9))
            h_small = max(2, int(pix.height / 7))
            img_small = img.resize((w_small, h_small), resample=Image.Resampling.BILINEAR)
            img_pix = img_small.resize((pix.width, pix.height), resample=Image.Resampling.NEAREST)
            
            img_bytes = io.BytesIO()
            img_pix.save(img_bytes, format="PNG")
            img_bytes.seek(0)
            imagenes_pixeladas.append((rect, img_bytes.getvalue()))

        # Borrado de texto interno con máscara blanca limpia
        for rect in rects_a_pixelar:
            page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions()

        # Insertar imagen pixelada en el espacio borrado
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
        with st.spinner("Pixelando apellidos, DNI y datos solicitante..."):
            pdf_limpio = censurar_pdf(uploaded_file.read())
            st.success("¡Documento procesado con éxito!")
            
            st.download_button(
                label="📥 Descargar PDF Limpio",
                data=pdf_limpio,
                file_name=uploaded_file.name.replace(".pdf", "_anonimizado.pdf"),
                mime="application/pdf"
            )
