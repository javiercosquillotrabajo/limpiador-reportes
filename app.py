import io
import re
import fitz  # PyMuPDF
from PIL import Image
import streamlit as st

st.set_page_config(page_title="Pixelador de Apellidos", page_icon="🔒", layout="centered")

st.title("🔒 Pixelador de Apellidos (Equifax / Experian)")
st.write("Identifica y pixela **únicamente el apellido paterno y materno**. Toda la demás información (DNI, fechas, nombres, etc.) queda visible.")

def identificar_apellidos(doc):
    """Detecta con exactitud los 2 apellidos (paterno y materno) del titular"""
    apellidos = set()
    
    for page in doc:
        words = page.get_text("words")
        
        # Agrupar palabras por línea horizontal
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

        # 1. Caso Experian: barra gris con guión (ej: DNI XXXXXXXX - CACERES YHUQUIMAGO NOE)
        for y_key, line_words in lineas.items():
            line_words.sort(key=lambda x: x[0])
            textos = [w[4] for w in line_words]
            
            if any("-" in t or "–" in t for t in textos) or any(t.upper() in ["DNI", "RUC"] for t in textos):
                idx_inicio = -1
                for i, w in enumerate(line_words):
                    if "-" in w[4] or "–" in w[4]:
                        idx_inicio = i + 1
                        break
                    # Si viene justo después de un número largo de DNI/RUC
                    num = re.sub(r'[^\w]', '', w[4])
                    if num.isdigit() and len(num) >= 8:
                        idx_inicio = i + 1

                if idx_inicio != -1 and idx_inicio < len(line_words):
                    candidatos = [
                        re.sub(r'[^A-ZÁÉÍÓÚÑa-z]', '', w[4]).upper() 
                        for w in line_words[idx_inicio:] 
                        if len(w[4]) > 1 and re.sub(r'[^A-ZÁÉÍÓÚÑa-z]', '', w[4]).isalpha()
                    ]
                    # En formato peruano, los primeros 2 son Paterno y Materno
                    if len(candidatos) >= 2:
                        apellidos.add(candidatos[0])
                        apellidos.add(candidatos[1])
                        return apellidos

        # 2. Caso con coma: PEREZ GARCIA, JUAN CARLOS
        blocks = page.get_text("blocks")
        for b in blocks:
            if b[6] != 0:
                continue
            for linea in b[4].splitlines():
                if "," in linea and not any(c in linea for c in ["/", "$", "S/."]):
                    partes = linea.split(",")
                    antes = [re.sub(r'[^A-ZÁÉÍÓÚÑa-z]', '', w).upper() for w in partes[0].split() if len(w) > 2]
                    if 1 <= len(antes) <= 2:
                        for a in antes:
                            apellidos.add(a)
                        return apellidos

        # 3. Caso con etiquetas: Apellido Paterno / Materno
        for b in blocks:
            if b[6] != 0:
                continue
            texto = b[4]
            pat_paterno = re.search(r'(?i)apellido\s+paterno[\s:]+([A-ZÁÉÍÓÚÑa-z]+)', texto)
            pat_materno = re.search(r'(?i)apellido\s+materno[\s:]+([A-ZÁÉÍÓÚÑa-z]+)', texto)
            if pat_paterno:
                apellidos.add(pat_paterno.group(1).upper())
            if pat_materno:
                apellidos.add(pat_materno.group(1).upper())
            if apellidos:
                return apellidos

    return apellidos

def censurar_pdf(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    
    # Identificar únicamente los apellidos paterno y materno
    apellidos_a_pixelar = identificar_apellidos(doc)
    
    for page in doc:
        rects_a_pixelar = []
        words = page.get_text("words")
        
        # Buscar SOLO las palabras que coinciden con los apellidos
        for w in words:
            palabra_limpia = re.sub(r'[^A-ZÁÉÍÓÚÑa-z]', '', w[4]).upper()
            if palabra_limpia in apellidos_a_pixelar:
                rects_a_pixelar.append(fitz.Rect(w[0], w[1], w[2], w[3]))

        # Aplicar el efecto de pixeleado exclusivamente sobre esas zonas
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

        # Borrado del texto del apellido
        for rect in rects_a_pixelar:
            page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions()

        # Insertar imagen pixelada en el espacio de los apellidos
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
    
    if st.button("🚀 Pixelar Apellidos"):
        with st.spinner("Identificando y pixelando únicamente apellidos..."):
            pdf_limpio = censurar_pdf(uploaded_file.read())
            st.success("¡Apellidos pixelados con éxito!")
            
            st.download_button(
                label="📥 Descargar PDF",
                data=pdf_limpio,
                file_name=uploaded_file.name.replace(".pdf", "_apellidos_pixelados.pdf"),
                mime="application/pdf"
            )
