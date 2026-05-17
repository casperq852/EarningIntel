import { useState } from 'react'

const KEY = 'earningintel_email'

export function useEmail() {
  const [email, setEmailState] = useState(() => localStorage.getItem(KEY) || '')

  const setEmail = (val) => {
    if (val) {
      localStorage.setItem(KEY, val)
    } else {
      localStorage.removeItem(KEY)
    }
    setEmailState(val)
  }

  return { email, setEmail }
}
