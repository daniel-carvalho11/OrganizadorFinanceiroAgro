import os
import asyncio
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

# Importação do Agent1 conforme estrutura especificada na aula (Slide 16)
from agents.agent1.manipulacao_dados import Agent1

load_dotenv()

app = FastAPI(title="Processador de NF - N2 Etapa 1")
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")

@app.post("/api/extrair-nf")
async def extrair_nota_fiscal(
    file: UploadFile = File(...), 
    api_key: Optional[str] = Form(None)
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="O arquivo enviado deve ser um documento PDF.")

    if not api_key:
        raise HTTPException(status_code=400, detail="A chave da API do Gemini é obrigatória.")

    try:
        pdf_bytes = await file.read()
        
        # Instancia o Agent1 passando a chave da API fornecida via interface
        agent1 = Agent1(api_key=api_key)
        
        # Execução do agente de extração (Slide 16)
        dados_json = await asyncio.to_thread(agent1.extrair_dados, pdf_bytes)
        
        return JSONResponse(content={"status": "success", "dados": dados_json})

    except ValueError as ve:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(ve)}
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Falha ao processar Nota Fiscal: {str(e)}"}
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)