from fastapi import APIRouter, Depends, HTTPException

from vazhi.services import graph_service

from server.auth import require_uid

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("/{kb_id}/subgraph")
async def get_subgraph(kb_id: str, max_nodes: int = 200, uid: str = Depends(require_uid)):
    try:
        return await graph_service.get_subgraph(uid=uid, kb_id=kb_id, max_nodes=max_nodes)
    except PermissionError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
