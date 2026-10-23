"""Customer address endpoints (Level 4)."""
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import pagination, require_customer
from app.models.user import User
from app.schemas.common import Page
from app.schemas.restaurant import AddressCreate, AddressOut, AddressUpdate
from app.services import address_service
from app.utils.pagination import PageParams

router = APIRouter(prefix="/addresses", tags=["Addresses"])


@router.post("", response_model=AddressOut, status_code=status.HTTP_201_CREATED)
def create_address(data: AddressCreate, customer: User = Depends(require_customer), db: Session = Depends(get_db)):
    return address_service.create_address(db, customer, data)


@router.get("", response_model=Page[AddressOut])
def list_addresses(
    page: PageParams = Depends(pagination), customer: User = Depends(require_customer), db: Session = Depends(get_db)
):
    total, rows = address_service.list_addresses(db, customer, page.skip, page.limit)
    return Page(total=total, skip=page.skip, limit=page.limit, items=[AddressOut.model_validate(a) for a in rows])


@router.put("/{address_id}", response_model=AddressOut)
def update_address(
    address_id: int, data: AddressUpdate, customer: User = Depends(require_customer), db: Session = Depends(get_db)
):
    return address_service.update_address(db, customer, address_id, data)


@router.delete("/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_address(address_id: int, customer: User = Depends(require_customer), db: Session = Depends(get_db)):
    address_service.delete_address(db, customer, address_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{address_id}/default", response_model=AddressOut)
def make_default(address_id: int, customer: User = Depends(require_customer), db: Session = Depends(get_db)):
    return address_service.set_default_address(db, customer, address_id)
