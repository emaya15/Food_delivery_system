"""Customer address management (multiple addresses, exactly one default)."""
from typing import List

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.database import transaction
from app.models.address import Address
from app.models.user import User
from app.schemas.restaurant import AddressCreate, AddressUpdate
from app.utils.errors import NotFoundError


def get_own_address(db: Session, customer: User, address_id: int) -> Address:
    """Return the address only if it belongs to the customer (404 otherwise, never leak others')."""
    address = db.get(Address, address_id)
    if address is None or address.customer_id != customer.id:
        raise NotFoundError("Address not found")
    return address


def _clear_defaults(db: Session, customer_id: int, except_id: int = 0) -> None:
    db.execute(
        update(Address)
        .where(Address.customer_id == customer_id, Address.is_default.is_(True), Address.id != except_id)
        .values(is_default=False)
    )


def create_address(db: Session, customer: User, data: AddressCreate) -> Address:
    with transaction(db):
        count = db.scalar(select(func.count(Address.id)).where(Address.customer_id == customer.id)) or 0
        make_default = data.is_default or count == 0  # the first address is the default
        address = Address(customer_id=customer.id, **data.model_dump(exclude={"is_default"}), is_default=False)
        db.add(address)
        db.flush()
        if make_default:
            _clear_defaults(db, customer.id, except_id=address.id)
            address.is_default = True
        db.flush()
    return address


def list_addresses(db: Session, customer: User, skip: int, limit: int):
    stmt = select(Address).where(Address.customer_id == customer.id)
    total = db.scalar(select(func.count(Address.id)).where(Address.customer_id == customer.id)) or 0
    rows: List[Address] = list(
        db.scalars(stmt.order_by(Address.is_default.desc(), Address.id).offset(skip).limit(limit))
    )
    return total, rows


def update_address(db: Session, customer: User, address_id: int, data: AddressUpdate) -> Address:
    address = get_own_address(db, customer, address_id)
    changes = data.model_dump(exclude_unset=True)
    with transaction(db):
        for key, value in changes.items():
            if value is not None:
                setattr(address, key, value)
        db.flush()
    return address


def delete_address(db: Session, customer: User, address_id: int) -> None:
    """Delete an address; if it was the default, promote the oldest remaining one."""
    address = get_own_address(db, customer, address_id)
    was_default = address.is_default
    with transaction(db):
        db.delete(address)
        db.flush()
        if was_default:
            nxt = db.scalar(select(Address).where(Address.customer_id == customer.id).order_by(Address.id).limit(1))
            if nxt is not None:
                nxt.is_default = True
                db.flush()


def set_default_address(db: Session, customer: User, address_id: int) -> Address:
    address = get_own_address(db, customer, address_id)
    with transaction(db):
        _clear_defaults(db, customer.id, except_id=address.id)
        address.is_default = True
        db.flush()
    return address
