
def register_event(db, event, *, session):
    db["outbox"].insert_one(event, session=session)