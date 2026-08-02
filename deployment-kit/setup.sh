#!/bin/bash
# =============================================================================
# Tales Setup Helper Script
# =============================================================================
# This script helps you set up Tales by:
# 1. Checking prerequisites (Docker, Docker Compose)
# 2. Creating .env from template if needed
# 3. Generating secure random keys
# 4. Starting the application
# =============================================================================

set -e

echo "============================================="
echo "  Tales Setup Helper"
echo "============================================="
echo ""

# Check for Docker
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker is not installed."
    echo "Please install Docker first: https://docs.docker.com/get-docker/"
    exit 1
fi

# Check for Docker Compose
if ! docker compose version &> /dev/null; then
    echo "ERROR: Docker Compose is not installed or not working."
    echo "Please install Docker Compose: https://docs.docker.com/compose/install/"
    exit 1
fi

echo "Docker and Docker Compose found."
echo ""

# Check for .env file
if [ -f ".env" ]; then
    echo "Found existing .env file."
    read -p "Do you want to keep it? (y/n) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Backing up existing .env to .env.backup"
        mv .env .env.backup
        cp .env.template .env
        echo "Created new .env from template."
    fi
else
    if [ -f ".env.template" ]; then
        cp .env.template .env
        echo "Created .env from template."
    else
        echo "ERROR: .env.template not found."
        echo "Please ensure .env.template is in the same directory as this script."
        exit 1
    fi
fi

echo ""

# Generate security keys
echo "Generating security keys..."

# APP_SECRET can be any random string. ENCRYPTION_KEY must be a valid Fernet
# key: exactly 32 url-safe base64-encoded bytes, which is 44 characters with
# the trailing '=' padding intact. secrets.token_urlsafe(32) produces 43
# characters and Fernet rejects it, so do not use it here. Stripping the '='
# from an openssl base64 string breaks it the same way.
if command -v python3 &> /dev/null; then
    JWT_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    ENC_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null) \
        || ENC_KEY=$(python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
elif command -v python &> /dev/null; then
    JWT_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
    ENC_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null) \
        || ENC_KEY=$(python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
else
    # Fallback to openssl if Python not available. Note the padding is kept.
    JWT_KEY=$(openssl rand -base64 32 | tr -d '=' | tr '+/' '-_')
    ENC_KEY=$(openssl rand -base64 32 | tr '+/' '-_')
fi

# Update .env with generated keys (only if they still have placeholder values)
# APP_SECRET is preferred, JWT_SECRET_KEY is supported for backwards compatibility
if grep -q "APP_SECRET=CHANGE_ME" .env; then
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s/APP_SECRET=CHANGE_ME.*/APP_SECRET=$JWT_KEY/" .env
    else
        sed -i "s/APP_SECRET=CHANGE_ME.*/APP_SECRET=$JWT_KEY/" .env
    fi
    echo "Generated APP_SECRET"
elif grep -q "JWT_SECRET_KEY=CHANGE_ME" .env; then
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s/JWT_SECRET_KEY=CHANGE_ME.*/JWT_SECRET_KEY=$JWT_KEY/" .env
    else
        sed -i "s/JWT_SECRET_KEY=CHANGE_ME.*/JWT_SECRET_KEY=$JWT_KEY/" .env
    fi
    echo "Generated JWT_SECRET_KEY"
fi

if grep -q "ENCRYPTION_KEY=CHANGE_ME" .env; then
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s/ENCRYPTION_KEY=CHANGE_ME.*/ENCRYPTION_KEY=$ENC_KEY/" .env
    else
        sed -i "s/ENCRYPTION_KEY=CHANGE_ME.*/ENCRYPTION_KEY=$ENC_KEY/" .env
    fi
    echo "Generated ENCRYPTION_KEY"
fi

echo ""

# Check for LLM API keys
echo "Checking for LLM API keys..."
HAS_LLM_KEY=false

if grep -q "GEMINI_API_KEY=." .env && ! grep -q "GEMINI_API_KEY=$" .env; then
    # Check if it's not just empty or placeholder
    GEMINI_VAL=$(grep "GEMINI_API_KEY=" .env | cut -d'=' -f2)
    if [ -n "$GEMINI_VAL" ] && [ "$GEMINI_VAL" != "" ]; then
        echo "  Found: GEMINI_API_KEY"
        HAS_LLM_KEY=true
    fi
fi

if grep -q "OPENAI_API_KEY=." .env && ! grep -q "OPENAI_API_KEY=$" .env; then
    OPENAI_VAL=$(grep "OPENAI_API_KEY=" .env | cut -d'=' -f2)
    if [ -n "$OPENAI_VAL" ] && [ "$OPENAI_VAL" != "" ]; then
        echo "  Found: OPENAI_API_KEY"
        HAS_LLM_KEY=true
    fi
fi

if grep -q "ANTHROPIC_API_KEY=." .env && ! grep -q "ANTHROPIC_API_KEY=$" .env; then
    ANTHROPIC_VAL=$(grep "ANTHROPIC_API_KEY=" .env | cut -d'=' -f2)
    if [ -n "$ANTHROPIC_VAL" ] && [ "$ANTHROPIC_VAL" != "" ]; then
        echo "  Found: ANTHROPIC_API_KEY"
        HAS_LLM_KEY=true
    fi
fi

if grep -q "PERPLEXITY_API_KEY=." .env && ! grep -q "PERPLEXITY_API_KEY=$" .env; then
    PERPLEXITY_VAL=$(grep "PERPLEXITY_API_KEY=" .env | cut -d'=' -f2)
    if [ -n "$PERPLEXITY_VAL" ] && [ "$PERPLEXITY_VAL" != "" ]; then
        echo "  Found: PERPLEXITY_API_KEY"
        HAS_LLM_KEY=true
    fi
fi

if [ "$HAS_LLM_KEY" = false ]; then
    echo ""
    echo "WARNING: No LLM API keys found in .env"
    echo "You need at least one LLM API key to use Tales."
    echo ""
    echo "Edit .env and add at least one of:"
    echo "  GEMINI_API_KEY=your-key    (recommended)"
    echo "  OPENAI_API_KEY=your-key"
    echo "  ANTHROPIC_API_KEY=your-key"
    echo "  PERPLEXITY_API_KEY=your-key"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Setup paused. Edit .env and run this script again."
        exit 0
    fi
fi

echo ""

# Ask about starting
read -p "Start Tales now? (y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "Starting Tales..."
    docker compose up -d

    echo ""
    echo "Waiting for containers to start..."
    sleep 10

    # Check if containers are running
    if docker compose ps | grep -q "Up"; then
        echo ""
        echo "============================================="
        echo "  Tales is starting!"
        echo "============================================="
        echo ""
        echo "Next steps:"
        echo ""
        echo "1. Create an admin account:"
        echo "   docker compose exec app python scripts/admin/setup_initial_admin.py"
        echo ""
        echo "2. Open your browser to: http://localhost:8080"
        echo ""
        echo "3. Log in with your admin credentials"
        echo ""
        echo "For logs: docker compose logs -f app"
        echo "To stop:  docker compose down"
        echo ""
    else
        echo ""
        echo "WARNING: Containers may not have started correctly."
        echo "Check logs with: docker compose logs"
        echo ""
    fi
else
    echo ""
    echo "============================================="
    echo "  Setup Complete"
    echo "============================================="
    echo ""
    echo "Your .env file is ready. To start Tales:"
    echo ""
    echo "1. Add your LLM API key(s) to .env"
    echo "2. Run: docker compose up -d"
    echo "3. Create admin: docker compose exec app python scripts/admin/setup_initial_admin.py"
    echo "4. Open: http://localhost:8080"
    echo ""
fi
