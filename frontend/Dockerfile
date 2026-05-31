FROM node:20-slim

WORKDIR /app

# Install dependencies first for better layer caching.
COPY package.json package-lock.json* ./
RUN npm install

# Copy the rest of the app.
COPY . .

ENV HOST=0.0.0.0
ENV PORT=3000
ENV BROWSER=none

EXPOSE 3000

CMD ["npm", "start"]
