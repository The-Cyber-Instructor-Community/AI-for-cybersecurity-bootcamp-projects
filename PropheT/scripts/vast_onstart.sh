apt-get update -qq; apt-get install -y -qq curl ca-certificates > /dev/null;
command -v ollama > /dev/null || curl -fsSL https://ollama.com/install.sh | sh;
export OLLAMA_HOST=127.0.0.1:11434 OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 OLLAMA_CONTEXT_LENGTH=32768 OLLAMA_KEEP_ALIVE=-1;
( nohup ollama serve > /root/ollama.log 2>&1 & );
sleep 8;
( nohup ollama pull qwen3:30b-a3b-instruct-2507-q4_K_M > /root/pull.log 2>&1 & );
