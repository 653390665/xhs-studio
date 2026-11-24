import { Result } from "antd";

/**
 * Last-resort route for unknown `/platforms/xhs/:section` paths.
 * Known legacy sections are redirected in router.tsx instead of rendering
 * a static placeholder, so this page only handles genuinely unknown URLs.
 */
export function XhsSectionPage() {
  return (
    <Result
      status="404"
      title="页面不存在"
      subTitle="这个路径没有对应功能，可能已经迁移或删除。请从左侧导航重新进入。"
    />
  );
}
