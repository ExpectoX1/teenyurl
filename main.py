from fastapi import FastAPI, HTTPException, Request, status
from database import connection_pool
from cache import r
from pydantic import BaseModel, HttpUrl, field_validator
import uuid
from fastapi.responses import RedirectResponse, JSONResponse
from dotenv import load_dotenv
import os


app = FastAPI()
load_dotenv()


HOST_NAME = os.getenv("BASE_URL")

def rate_limit(request:Request):
    client_host = request.client.host if request.client else "Unknown"
    redis_key = "rl"+client_host
    count = r.incr(redis_key)
    if count == 1:
        r.expire(redis_key, 60)
        return False
    if count >10:
        return True
       
def get_and_validate_code(url: str):
    conn = connection_pool.getconn()
    cur = conn.cursor()
    cur.execute(
    "SELECT code FROM url_map WHERE original_url = %s",(url,))
    result = cur.fetchone()
    if result:
        cur.close()
        connection_pool.putconn(conn)
        return (result[0], False)
    else:
        code = str(uuid.uuid4())[:8]
        cur.execute(
        "SELECT code FROM url_map WHERE code = %s",(code,))
        if cur.fetchone():
            cur.close()
            connection_pool.putconn(conn)
            return get_and_validate_code(url)
        else:
            cur.close()
            connection_pool.putconn(conn)
            return (code,True)

class Url(BaseModel):
    url: HttpUrl
    @field_validator("url", mode="before")
    @classmethod
    def strip_whitespace(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("URL cannot be empty")
        return value

@app.post("/shorten")
def shorten_url(request:Request , url: Url):
    res = rate_limit(request)
    if res :
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, 
            detail="yo you got ratelimited my boi"
        )
    original_url = str(url.url)
    code, isNew = get_and_validate_code(original_url)
    if isNew:
        conn = connection_pool.getconn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO url_map (original_url, code) VALUES (%s, %s)",
            (original_url, code),
        )
        conn.commit()
        cur.close()
        connection_pool.putconn(conn)
    return JSONResponse(
        content={"url": original_url, "short_url": f"{HOST_NAME}/{code}"},
        status_code=status.HTTP_201_CREATED if isNew else status.HTTP_200_OK,
    )


@app.get("/{code}")
def fetch_and_redirect(code):
    conn = connection_pool.getconn()
    cur = conn.cursor()
    cur.execute("SELECT original_url FROM url_map WHERE code=%s", (code,))
    record = cur.fetchone()
    if record:
        cur.execute('''
                INSERT INTO teeny_clicks (url_id) 
                SELECT id FROM url_map WHERE code = %s
            ''',(code,))
        conn.commit()
        cur.close()
        connection_pool.putconn(conn)
        return RedirectResponse(record[0], status_code = 301)
    else:
        cur.close()
        connection_pool.putconn(conn)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="teenyurl not found"
        )

@app.get("/stats/{code}")
def get_code_stats(code):
    conn = connection_pool.getconn()
    cur = conn.cursor()
    cur.execute('''
        SELECT COUNT(*) 
        FROM teeny_clicks 
        JOIN url_map ON teeny_clicks.url_id = url_map.id
        WHERE code = %s
    ''',(code,))
    result = cur.fetchone()
    if result[0] == 0:
        cur.execute('SELECT id FROM url_map where code=%s ',(code,))
        res= cur.fetchone()
        if res:
            cur.close()
            connection_pool.putconn(conn)
            return JSONResponse(
                content={"code":code, "clicks": 0 },
                status_code=status.HTTP_200_OK,)
        else:
            cur.close()
            connection_pool.putconn(conn)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="Code does not exist")
    else:
        cur.close()
        connection_pool.putconn(conn)
        return JSONResponse(
        content={"code":code, "clicks": result[0] },
        status_code=status.HTTP_200_OK,
    )




