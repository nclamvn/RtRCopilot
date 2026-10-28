// Share only the neutral scoped BFF, never the legacy app root/proxy/auth.
export {GET, POST} from "../../../../../../web/src/app/api/workspace/[[...path]]/route";
