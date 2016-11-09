FROM tampalab2-laniakea.vici.verizon.com:9000/montana/ts-python:2.7.10

RUN pip install web.py

ADD . /app/

WORKDIR /app/

CMD ["sh", "-c", "python testifyui.py 80"]
