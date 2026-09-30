# ---- stage 1: build the patched Luau runtime + luau-ast (Luau 0.739) ----
FROM python:3.11-slim-bookworm AS luau
RUN apt-get update \
 && apt-get install -y --no-install-recommends git cmake g++ make ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /build
# build_luau.py carries the one patch the engine needs (writable vector metatable)
COPY deobf/build_luau.py ./build_luau.py
RUN git clone -q --depth 1 --branch 0.739 https://github.com/luau-lang/luau.git luau \
 && python -c "import build_luau; build_luau.patch('luau')" \
 && cmake -S luau -B luau/build -DCMAKE_BUILD_TYPE=Release -DLUAU_BUILD_TESTS=OFF \
      -DCMAKE_C_FLAGS_RELEASE="-O2 -DNDEBUG" -DCMAKE_CXX_FLAGS_RELEASE="-O2 -DNDEBUG" \
 && cmake --build luau/build --target Luau.Repl.CLI Luau.Ast.CLI --parallel 2 \
 && echo 'print("luau ok")' > t.lua && ./luau/build/luau t.lua \
 && test -x luau/build/luau-ast

# ---- stage 2: runtime ----
FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 bot
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=bot:bot deobf ./deobf
COPY --chown=bot:bot bot.py runner.py ./
COPY --from=luau --chown=bot:bot /build/luau/build/luau /app/deobf/bin/luau
COPY --from=luau --chown=bot:bot /build/luau/build/luau-ast /app/deobf/bin/luau-ast
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS=ignore
USER bot
CMD ["python", "bot.py"]
