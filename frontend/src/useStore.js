import { createContext, useContext } from 'react'

export const Store = createContext(null)
export const useStore = () => useContext(Store)
