FROM alpine:3.19

WORKDIR /action

RUN apk add --no-cache \
    python3 \
    py3-pip \
    git \
    && ln -sf python3 /usr/bin/python

COPY requirements.txt .
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

COPY check_holiday_updates.py issue_body_template.md .

RUN chmod +x check_holiday_updates.py

ENTRYPOINT ["python", "/action/check_holiday_updates.py"]
