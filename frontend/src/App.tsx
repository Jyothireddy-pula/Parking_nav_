import { Navigate as RouterNavigate, Route, Routes } from "react-router-dom";

import NavigateScreen from "./Navigate";

function AdminRouteGuard() {
  const isAuthenticated = false;
  return isAuthenticated ? <div>Admin workspace</div> : <RouterNavigate replace to="/" />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<NavigateScreen />} />
      <Route path="/admin/*" element={<AdminRouteGuard />} />
      <Route path="*" element={<RouterNavigate replace to="/" />} />
    </Routes>
  );
}
