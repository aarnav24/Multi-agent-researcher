import NextAuth from "next-auth"
import CredentialsProvider from "next-auth/providers/credentials"

export const { handlers, signIn, signOut, auth } = NextAuth({
  providers: [
    CredentialsProvider({
      name: "Credentials",
      credentials: {
        username: { label: "Username", type: "text" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials: any) {
        const username = credentials?.username || ""
        const password = credentials?.password || ""

        if (String(username).length < 3 || String(password).length < 6) {
          return null
        }

        // Backend API URL
        const API_BASE = process.env.BACKEND_URL || "http://localhost:8000"

        try {
          // Try to login
          let res = await fetch(`${API_BASE}/api/v1/auth/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password }),
          })

          // If login fails (user doesn't exist yet, e.g. first Google sign-in), try to create
          if (!res.ok && username.length === 21) {
            // Google UIDs are 21 chars — create account on-the-fly
            await fetch(`${API_BASE}/api/v1/auth/signup`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                username,
                password,
                name: "Google User",
              }),
            }).catch(() => {})
            // Try login again
            res = await fetch(`${API_BASE}/api/v1/auth/login`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ username, password }),
            })
          }

          if (res.ok) {
            const data = await res.json()
            const user = data.user
            return { id: user.id, name: user.name, email: user.email || null }
          }
        } catch (e) {
          console.error("Auth login failed:", e)
        }
        return null
      },
    }),
  ],
  pages: {
    signIn: "/login",
  },
  session: {
    strategy: "jwt" as const,
    maxAge: 24 * 60 * 60,
  },
  callbacks: {
    async jwt({ token, user }: { token: any; user: any }) {
      if (user) {
        token.name = user.name
        token.email = user.email
        token.uid = user.id
      }
      return token
    },
    async session({ session, token }: { session: any; token: any }) {
      if (session.user) {
        session.user.id = token.uid
        session.user.name = token.name
        session.user.email = token.email
      }
      return session
    },
  },
  secret: process.env.NEXTAUTH_SECRET || "dev-secret-change-in-production-12345",
})
