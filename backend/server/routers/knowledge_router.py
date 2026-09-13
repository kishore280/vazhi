import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from vazhi.services import eval_run_service, knowledge_service

from server.auth import require_uid

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class CreateKnowledgeBaseRequest(BaseModel):
    name: str


class RunEvaluationRequest(BaseModel):
    num_questions: int = 5


class IngestDocumentRequest(BaseModel):
    content: str
    filename: str = "document.md"
    preset_id: str = "general"
    parser_config: dict | None = None


class QueryKnowledgeBaseRequest(BaseModel):
    query_text: str
    top_k: int = 3


@router.get("/databases")
async def list_knowledge_bases(uid: str = Depends(require_uid)):
    kbs = await knowledge_service.list_knowledge_bases(uid=uid)
    return {"databases": [kb.to_dict() for kb in kbs]}


@router.post("/databases")
async def create_knowledge_base(body: CreateKnowledgeBaseRequest, uid: str = Depends(require_uid)):
    kb = await knowledge_service.create_knowledge_base(uid=uid, name=body.name)
    return kb.to_dict()


@router.post("/databases/{kb_id}/documents")
async def ingest_document(kb_id: str, body: IngestDocumentRequest, uid: str = Depends(require_uid)):
    try:
        await knowledge_service.ingest_document(
            uid=uid,
            kb_id=kb_id,
            doc_id=uuid.uuid4().hex,
            content=body.content,
            filename=body.filename,
            preset_id=body.preset_id,
            parser_config=body.parser_config,
        )
    except PermissionError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"status": "ingested"}


@router.get("/databases/{kb_id}/documents")
async def list_documents(kb_id: str, uid: str = Depends(require_uid)):
    try:
        documents = await knowledge_service.list_documents(uid=uid, kb_id=kb_id)
    except PermissionError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"documents": documents}


@router.post("/databases/{kb_id}/query")
async def query_knowledge_base(kb_id: str, body: QueryKnowledgeBaseRequest, uid: str = Depends(require_uid)):
    try:
        results = await knowledge_service.query_knowledge_base(
            uid=uid, kb_id=kb_id, query_text=body.query_text, top_k=body.top_k
        )
    except PermissionError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"results": results}


@router.post("/databases/{kb_id}/eval")
async def run_evaluation(kb_id: str, body: RunEvaluationRequest, uid: str = Depends(require_uid)):
    try:
        return await eval_run_service.run_evaluation(uid=uid, kb_id=kb_id, num_questions=body.num_questions)
    except PermissionError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/databases/{kb_id}/eval")
async def list_evaluation_runs(kb_id: str, uid: str = Depends(require_uid)):
    try:
        runs = await eval_run_service.list_evaluation_runs(uid=uid, kb_id=kb_id)
    except PermissionError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"runs": runs}
