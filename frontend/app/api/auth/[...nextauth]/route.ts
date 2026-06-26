import NextAuth from "next-auth"
import CredentialsProvider from "next-auth/providers/credentials"

const handler = NextAuth({
  providers: [
    CredentialsProvider({
      name: "Credentials",
      credentials: {
        username: { label: "Username", type: "text" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        // Simple auth — in production, verify against database
        const username = credentials?.username || ""
        const password = credentials?.password || ""

        // Demo auth: accept any non-empty credentials
        // Replace with real auth (bcrypt + DB lookup)
        if (username.length >= 3 && password.length >= 6) {
          return { id: username, name: username, email: `${username}@research.local` }
        }
        return null
      },
    }),
  ],
  pages: {
    signIn: "/login",
  },
  session: {
    strategy: "jwt",
    maxAge: 24 * 60 * 60, // 24 hours
  },
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.name = user.name
      }
      return token
    },
    async session({ session, token }) {
      if (session.user) {
        session.user.name = token.name as string
      }
      return session
    },
  },
  secret: process.env.NEXTAUTH_SECRET || "dev-secret-change-in-production-12345",
})

export { handler as GET, handler as POST }
